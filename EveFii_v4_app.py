# EveFii_v4_app.py - Versão FINAL, Completa e Funcional (Cálculo de Metas e Foco em Nutrição/Alimentos)

# Imports
import streamlit as st
import sqlite3
import hashlib
import os
import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime
from pulp import LpProblem, LpMinimize, LpVariable, PULP_CBC_CMD, LpStatus, value, lpSum 

# --- Configuração e Funções de Utilitário ---
DB_PATH = "evefii_v4.db"
PHOTOS_DIR = "photos" 

# Fatores para cálculo do Gasto Energético Total (GET) / TDEE
TDEE_FACTORS = {
    "Sedentário (pouco ou nenhum exercício)": 1.2,
    "Levemente Ativo (exercício 1-3 dias/semana)": 1.375,
    "Moderadamente Ativo (exercício 3-5 dias/semana)": 1.55,
    "Muito Ativo (exercício 6-7 dias/semana)": 1.725,
    "Extremamente Ativo (treino diário intenso e trabalho físico)": 1.9
}

# 1. Conexão do Banco de Dados
def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

# 2. Inicialização do Banco de Dados (Cria as 3 Tabelas Cruciais)
@st.cache_resource
def init_db():
    conn = get_conn(); cur = conn.cursor()
    
    cur.execute('CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE, password_hash TEXT)')
    
    # Tabela 2: Alimentos (sem foco em custo)
    cur.execute('''
        CREATE TABLE IF NOT EXISTS recipes (
            id INTEGER PRIMARY KEY AUTOINCREMENT, 
            name TEXT UNIQUE, 
            cost REAL, 
            calories INTEGER, 
            protein REAL, 
            carbs REAL, 
            fat REAL
        )
    ''')
    
    cur.execute('CREATE TABLE IF NOT EXISTS inventory (id INTEGER PRIMARY KEY AUTOINCREMENT, item TEXT UNIQUE, quantity REAL, unit TEXT)')
    
    # Adiciona usuário padrão se o banco estiver vazio
    cur.execute("SELECT COUNT(*) FROM users"); c = cur.fetchone()[0]
    if c == 0:
        pw = hashlib.sha256('change-me'.encode()).hexdigest()
        cur.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)", ('eve', pw))
    
    conn.commit()
    conn.close()

# 3. Funções de Criptografia e Verificação
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def verify_user(username, password):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT password_hash FROM users WHERE username = ?", (username,))
    user = cur.fetchone()
    conn.close()
    if user:
        return user[0] == hash_password(password)
    return False

# 4. Funções de Alimentos (antigas receitas) - Custo é 0.0 e Ignorado
def save_food(name, cal, prot, carb, fat):
    conn = get_conn(); cur = conn.cursor()
    try:
        cur.execute("INSERT INTO recipes (name, cost, calories, protein, carbs, fat) VALUES (?, 0.0, ?, ?, ?, ?)", 
                    (name, cal, prot, carb, fat))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def get_all_foods():
    conn = get_conn(); 
    foods = pd.read_sql("SELECT id, name, cost, calories, protein, carbs, fat FROM recipes", conn)
    conn.close()
    return foods

# 5. Funções de Inventário
def save_inventory_item(item, quantity, unit):
    conn = get_conn(); cur = conn.cursor()
    try:
        cur.execute("INSERT OR REPLACE INTO inventory (item, quantity, unit) VALUES (?, ?, ?)", 
                    (item, quantity, unit))
        conn.commit()
        return True
    except Exception:
        return False
    finally:
        conn.close()

def get_inventory():
    conn = get_conn(); 
    inventory = pd.read_sql("SELECT item, quantity, unit FROM inventory", conn)
    conn.close()
    return inventory

# --- Cálculo da TMB e Macros (NOVA LÓGICA) ---

def calculate_tdee_and_macros(gender, weight, height, age, activity_level_factor, prot_perc, carb_perc, fat_perc):
    # Fórmula de Mifflin-St Jeor (mais precisa que a de Harris-Benedict)
    if gender == 'Masculino':
        tmb = (10 * weight) + (6.25 * height) - (5 * age) + 5
    else: # Feminino
        tmb = (10 * weight) + (6.25 * height) - (5 * age) - 161
        
    tdee = tmb * activity_level_factor
    
    # Conversão para gramas (4 kcal/g para Prot/Carb, 9 kcal/g para Fat)
    target_prot = (tdee * (prot_perc / 100)) / 4
    target_carbs = (tdee * (carb_perc / 100)) / 4
    target_fat = (tdee * (fat_perc / 100)) / 9
    
    return int(tdee), int(target_prot), int(target_carbs), int(target_fat)


# --- Estrutura das Páginas do Aplicativo (Lógica Principal) ---

def page_planejador_inteligente():
    st.header("🧠 Planejador Inteligente (Cálculo de Metas + Otimização)")
    st.info("Calcule suas metas nutricionais e gere um plano de alimentos para atingi-las.")
    
    df_foods = get_all_foods()
    
    if df_foods.empty:
        st.warning("🚨 Por favor, cadastre alimentos na página 'Banco de Alimentos (TACO)' antes de otimizar.")
        return

    # --- 1. Cálculo de Metas (NOVA SEÇÃO) ---
    st.subheader("1. Cálculo de Metas Nutricionais")
    
    with st.form("metas_calc_form"):
        col1, col2, col3 = st.columns(3)
        with col1:
            gender = st.selectbox("Gênero", ['Masculino', 'Feminino'])
            weight = st.number_input("Peso (kg)", min_value=30.0, value=70.0, format="%.1f")
            prot_perc = st.number_input("Proteína (%)", min_value=10, max_value=40, value=25)
        with col2:
            height = st.number_input("Altura (cm)", min_value=100, value=170)
            age = st.number_input("Idade (anos)", min_value=15, value=30)
            carb_perc = st.number_input("Carboidratos (%)", min_value=30, max_value=70, value=50)
        with col3:
            activity_level = st.selectbox("Nível de Atividade", list(TDEE_FACTORS.keys()))
            fat_perc = st.number_input("Gordura (%)", min_value=10, max_value=40, value=25)
            
        # Verifica se a soma das porcentagens é 100
        total_perc = prot_perc + carb_perc + fat_perc
        if total_perc != 100:
            st.error(f"A soma dos macros deve ser 100%. Soma atual: {total_perc}%")
        
        num_days = st.number_input("Número de Dias no Plano", min_value=1, max_value=7, value=3)
        
        submitted_calc = st.form_submit_button("Calcular Metas e Otimizar", type="primary")

    if submitted_calc and total_perc == 100:
        activity_factor = TDEE_FACTORS[activity_level]
        
        target_cal, target_prot, target_carbs, target_fat = calculate_tdee_and_macros(
            gender, weight, height, age, activity_factor, prot_perc, carb_perc, fat_perc
        )
        
        # Exibe os resultados do cálculo
        st.subheader("Suas Metas Diárias Calculadas:")
        col_c, col_p, col_ca, col_g = st.columns(4)
        col_c.metric("Calorias (GET)", f"{target_cal} kcal")
        col_p.metric("Proteína (g)", f"{target_prot} g")
        col_ca.metric("Carboidratos (g)", f"{target_carbs} g")
        col_g.metric("Gordura (g)", f"{target_fat} g")
        st.markdown("---")


        # --- 2. LÓGICA DE OTIMIZAÇÃO (USANDO OS VALORES CALCULADOS) ---
        foods = df_foods['name'].tolist()
        
        # Alvos Totais para o período:
        total_target_cal = target_cal * num_days
        total_target_prot = target_prot * num_days
        total_target_carbs = target_carbs * num_days
        total_target_fat = target_fat * num_days

        # Variáveis de Decisão: Número de porções (ou vezes) que cada alimento será usado
        food_vars = LpVariable.dicts("Alimento", foods, 0, None, cat='Integer')

        # O problema: MINIMIZAR o desvio das Calorias
        prob = LpProblem("Otimizacao_Saude_EveFii", LpMinimize)
        
        # Variáveis de Desvio (Penalty)
        dev_cal_pos = LpVariable("Desvio_Calorias_Pos", 0) 
        dev_cal_neg = LpVariable("Desvio_Calorias_Neg", 0)

        # Restrição 1: A soma das calorias deve ser igual ao alvo, mais os desvios
        prob += lpSum(df_foods.loc[df_foods['name'] == r, 'calories'].iloc[0] * food_vars[r] for r in foods) + dev_cal_neg - dev_cal_pos == total_target_cal, "Restricao_Calorias"
        
        # Função Objetivo: Minimizar os desvios
        prob += dev_cal_pos + dev_cal_neg, "Minimizar_Desvio_Calorico"

        # Restrições de Nutrientes (Garantir um mínimo/máximo)
        prob += lpSum(df_foods.loc[df_foods['name'] == r, 'protein'].iloc[0] * food_vars[r] for r in foods) >= total_target_prot * 0.9, "Restricao_Proteina_Min"
        prob += lpSum(df_foods.loc[df_foods['name'] == r, 'carbs'].iloc[0] * food_vars[r] for r in foods) >= total_target_carbs * 0.9, "Restricao_Carbos_Min"
        prob += lpSum(df_foods.loc[df_foods['name'] == r, 'fat'].iloc[0] * food_vars[r] for r in foods) <= total_target_fat * 1.1, "Restricao_Gordura_Max"

        # Resolvendo o Problema
        with st.spinner("Resolvendo plano nutricional..."):
            prob.solve(PULP_CBC_CMD())
        
        # --- Visualização de Resultados ---
        st.subheader("3. Resultado do Plano Otimizado")
        
        if LpStatus[prob.status] == "Optimal":
            st.balloons()
            st.success("✅ Plano de dieta otimizado encontrado!")
            
            final_cal = value(lpSum(df_foods.loc[df_foods['name'] == r, 'calories'].iloc[0] * food_vars[r] for r in foods))
            
            st.metric("Calorias Totais no Plano", f"{final_cal:.0f} kcal (Alvo: {total_target_cal} kcal)")

            # Tabela de Resultados
            plan_data = []
            for v in prob.variables():
                if v.varValue > 0 and "Alimento" in v.name:
                    food_name = v.name.replace('Alimento_', '').replace('_', ' ')
                    plan_data.append({
                        'Alimento': food_name,
                        'Quantidade (Porções)': int(v.varValue),
                    })
            
            if plan_data:
                st.subheader("Sugestão de Dieta (Em porções):")
                st.dataframe(pd.DataFrame(plan_data), hide_index=True)
            else:
                st.warning("Plano otimizado, mas não foi possível encontrar um plano viável com as restrições de nutrientes.")

        else:
            st.error(f"❌ Otimização Falhou. Status: {LpStatus[prob.status]}. Não foi possível atingir as metas. Tente reduzir as metas de nutrientes ou adicionar mais alimentos.")


def page_receitas():
    st.header("🍚 Banco de Alimentos (Estilo TACO)")
    st.info("Cadastre alimentos crus ou porcionados (Ex: 'Arroz Cozido 100g') com seus nutrientes.")

    # --- Formulário de Cadastro ---
    st.subheader("Adicionar Novo Alimento")
    with st.form("nova_receita"):
        nome = st.text_input("Nome do Alimento e Porção (Ex: Frango Grelhado 120g)")
        
        col1, col2 = st.columns(2)
        with col1:
            calorias = st.number_input("Calorias (kcal)", min_value=0)
            proteina = st.number_input("Proteína (g)", min_value=0.0, format="%.1f")
        with col2:
            carboidratos = st.number_input("Carbohidratos (g)", min_value=0.0, format="%.1f")
            gordura = st.number_input("Gordura (g)", min_value=0.0, format="%.1f")
        
        submitted = st.form_submit_button("Salvar Alimento", type="primary")
        if submitted and nome:
            if save_food(nome, calorias, proteina, carboidratos, gordura):
                st.success(f"Alimento '{nome}' salvo com sucesso!")
            else:
                st.error(f"Erro: O alimento '{nome}' já existe. Por favor, use um nome diferente.")
    
    st.markdown("---")

    # --- Visualização dos Alimentos Salvos ---
    st.subheader("Alimentos Cadastrados")
    df_foods = get_all_foods()
    if not df_foods.empty:
        # Renomear e remover coluna Custo
        df_foods.columns = ['ID', 'Nome', 'Custo (R$)', 'Calorias (kcal)', 'Proteína (g)', 'Carbohidratos (g)', 'Gordura (g)']
        st.dataframe(df_foods[['Nome', 'Calorias (kcal)', 'Proteína (g)', 'Carbohidratos (g)', 'Gordura (g)']], hide_index=True)
    else:
        st.info("Nenhum alimento cadastrado ainda. Adicione alguns acima!")

def page_inventario():
    st.header("📦 Inventário e Lista de Compras")
    st.info("Gerencie o que você tem em estoque.")
    
    # --- Formulário de Inventário ---
    st.subheader("Adicionar/Atualizar Item no Inventário")
    with st.form("inventario_form"):
        item_name = st.text_input("Nome do Item (Ex: Arroz, Peito de Frango)")
        col1, col2 = st.columns(2)
        with col1:
            quantity = st.number_input("Quantidade", min_value=0.0, format="%.2f", value=0.0)
        with col2:
            unit = st.selectbox("Unidade", ['g', 'kg', 'ml', 'litros', 'unidades'])
        
        submitted = st.form_submit_button("Salvar/Atualizar Item", type="primary")
        if submitted and item_name:
            if save_inventory_item(item_name, quantity, unit):
                st.success(f"Item '{item_name}' atualizado com sucesso!")
            else:
                st.error("Erro ao salvar item.")
                
    st.markdown("---")

    # --- Visualização do Inventário ---
    st.subheader("Estoque Atual")
    df_inventory = get_inventory()
    if not df_inventory.empty:
        st.dataframe(df_inventory, hide_index=True)
    else:
        st.info("Seu inventário está vazio.")

def page_relatorios():
    st.header("📊 Relatórios e Análise de Nutrientes")
    st.info("Gráfico de análise de nutrientes.")
    
    st.subheader("Distribuição de Nutrientes Cadastrados")
    
    df_foods = get_all_foods()
    
    if df_foods.empty:
        st.warning("Cadastre alimentos para visualizar a análise.")
        return

    # Gráfico simples para mostrar a distribuição dos macros
    total_prot = df_foods['protein'].sum()
    total_carbs = df_foods['carbs'].sum()
    total_fat = df_foods['fat'].sum()
    
    data = [total_prot, total_carbs, total_fat]
    labels = ['Proteína', 'Carboidratos', 'Gordura']
    
    fig, ax = plt.subplots()
    ax.pie(data, labels=labels, autopct='%1.1f%%', startangle=90, colors=['#4CAF50', '#2196F3', '#FFC107'])
    ax.axis('equal') # Garante que o gráfico de pizza seja um círculo
    ax.set_title('Distribuição Total de Macronutrientes')
    
    st.pyplot(fig)


# --- Login e Roteamento Principal ---

def main_app():
    # Exibe o usuário logado na sidebar
    st.sidebar.markdown(f"**Usuário Logado:** `{st.session_state.get('username', 'N/A')}`")
    st.sidebar.markdown("---")
    
    PAGES = {
        "Planejador Inteligente": page_planejador_inteligente,
        "Banco de Alimentos (TACO)": page_receitas, 
        "Inventário": page_inventario,
        "Relatórios": page_relatorios
    }

    st.sidebar.title("EveFii v4 Completo (Nutrição)")
    selection = st.sidebar.radio("Navegação", list(PAGES.keys()))
    
    st.sidebar.markdown("---")
    if st.sidebar.button("Logout", type="secondary"):
        st.session_state['logged_in'] = False
        st.session_state.pop('username', None)
        st.rerun()

    PAGES[selection]()

def show_login():
    st.title("EveFii v4 — Focado em Nutrição")
    st.subheader("Faça Login para Continuar")
    
    # Uso de st.form para melhor controle do estado do Streamlit
    with st.form("login_form"):
        username = st.text_input("Usuário")
        password = st.text_input("Senha", type='password')
        login_submitted = st.form_submit_button("Login", type="primary")
        
        if login_submitted:
            if verify_user(username, password):
                st.session_state['logged_in'] = True
                st.session_state['username'] = username
                st.rerun()
            else:
                st.error("Usuário ou Senha inválidos. (Padrão: eve / change-me)")

# --- Início da Execução ---

if __name__ == "__main__":
    
    st.set_page_config(page_title="EveFii v4 Nutrição", layout="wide")
    
    # Inicializa o banco de dados e o usuário padrão (só roda uma vez por caching)
    init_db()
    
    # Cria o diretório de fotos, se necessário
    os.makedirs(PHOTOS_DIR, exist_ok=True)
    
    if 'logged_in' not in st.session_state:
        st.session_state['logged_in'] = False

    if st.session_state['logged_in']:
        main_app()
    else:
        show_login()
