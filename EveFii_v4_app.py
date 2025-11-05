# EveFii_v5_app.py - Versão FINAL (Foco em Gramas e Refeições)

# Imports
import streamlit as st
import sqlite3
import hashlib
import os
import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime
from pulp import LpProblem, LpMinimize, LpVariable, PULP_CBC_CMD, LpStatus, value, lpSum, const

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
    # OBS: Todos os nutrientes devem ser cadastrados para 100g.
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

# 5. Funções de Inventário (Não alteradas)
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

# --- Cálculo da TMB e Macros (LÓGICA INTELIGENTE) ---

def calculate_smart_macros(gender, weight, height, age, activity_level_factor, goal):
    # 1. Cálculo do TMB (Mifflin-St Jeor)
    if gender == 'Masculino':
        tmb = (10 * weight) + (6.25 * height) - (5 * age) + 5
    else: # Feminino
        tmb = (10 * weight) + (6.25 * height) - (5 * age) - 161
        
    get_tdee = tmb * activity_level_factor
    
    # 2. Ajuste de Calorias (GET Final)
    if goal == 'Déficit Calórico':
        final_cal = get_tdee - 500
        final_cal = max(final_cal, 1200)
        prot_multiplier = 2.0 
        fat_perc = 0.20
    elif goal == 'Hipertrofia Muscular':
        final_cal = get_tdee + 300
        prot_multiplier = 2.2 
        fat_perc = 0.25
    else: # Manutenção
        final_cal = get_tdee
        prot_multiplier = 1.8 
        fat_perc = 0.25

    final_cal = int(final_cal)
    
    # 3. Distribuição dos Macros em Gramas
    target_prot = int(weight * prot_multiplier) 
    target_fat = int((final_cal * fat_perc) / 9) 
    
    cal_from_prot_fat = (target_prot * 4) + (target_fat * 9) 
    cal_from_carbs = max(final_cal - cal_from_prot_fat, 400) 
    target_carbs = int(cal_from_carbs / 4)
    
    recalculated_cal = (target_prot * 4) + (target_carbs * 4) + (target_fat * 9)
    
    return int(recalculated_cal), target_prot, target_carbs, target_fat

# --- Estrutura das Páginas do Aplicativo (Lógica Principal) ---

def page_planejador_inteligente():
    st.header("🧠 Planejador Inteligente (Refeições e Gramas)")
    st.info("Otimize seu plano de alimentos em **gramas** para atingir as metas calculadas.")
    
    df_foods = get_all_foods()
    
    if df_foods.empty:
        st.warning("🚨 Por favor, cadastre alimentos na página 'Banco de Alimentos (TACO)' antes de otimizar.")
        return

    # --- 1. Cálculo de Metas ---
    st.subheader("1. Seus Dados e Objetivo")
    
    # ... (Cálculo de TMB e Macros: Código inalterado) ...
    with st.form("metas_calc_form"):
        col1, col2, col3 = st.columns(3)
        with col1:
            gender = st.selectbox("Gênero", ['Masculino', 'Feminino'])
            weight = st.number_input("Peso (kg)", min_value=30.0, value=75.0, format="%.1f")
            goal = st.selectbox("Objetivo", ['Manutenção', 'Déficit Calórico', 'Hipertrofia Muscular'])
        with col2:
            height = st.number_input("Altura (cm)", min_value=100, value=175)
            age = st.number_input("Idade (anos)", min_value=15, value=30)
            
        with col3:
            activity_level = st.selectbox("Nível de Atividade", list(TDEE_FACTORS.keys()))
            num_meals = st.number_input("Número de Refeições/Dia", min_value=2, max_value=6, value=4)
            
        submitted_calc = st.form_submit_button("Calcular Metas Diárias", type="primary")

    if submitted_calc:
        activity_factor = TDEE_FACTORS[activity_level]
        
        target_cal, target_prot, target_carbs, target_fat = calculate_smart_macros(
            gender, weight, height, age, activity_factor, goal
        )
        
        st.session_state['targets'] = {
            'cal': target_cal, 'prot': target_prot, 'carbs': target_carbs, 'fat': target_fat,
            'num_meals': num_meals, 'df_foods': df_foods
        }
        
        # Exibe os resultados do cálculo
        st.subheader("Suas Metas Diárias Calculadas:")
        col_c, col_p, col_ca, col_g = st.columns(4)
        col_c.metric("Calorias Alvo", f"{target_cal} kcal")
        col_p.metric("Proteína Alvo", f"{target_prot} g")
        col_ca.metric("Carboidratos Alvo", f"{target_carbs} g")
        col_g.metric("Gordura Alvo", f"{target_fat} g")
        st.markdown("---")
    
    
    # --- 2. Definição da Dieta por Refeição (NOVA LÓGICA DE PLANEJAMENTO) ---

    if 'targets' in st.session_state:
        targets = st.session_state['targets']
        
        st.subheader(f"2. Montagem do Plano de Refeições ({targets['num_meals']} Refeições)")
        st.info("Selecione os alimentos disponíveis para cada refeição. O sistema calculará a gramagem exata.")

        # Inicializa a lista de alimentos por refeição
        if 'meal_foods' not in st.session_state or len(st.session_state['meal_foods']) != targets['num_meals']:
            st.session_state['meal_foods'] = [[] for _ in range(targets['num_meals'])]

        meal_names = [f"Refeição {i+1}" for i in range(targets['num_meals'])]
        all_food_names = targets['df_foods']['name'].tolist()
        
        # Interface de seleção de alimentos
        for i, meal_name in enumerate(meal_names):
            with st.expander(f"🍽️ **{meal_name}** - Alimentos Selecionados: {len(st.session_state['meal_foods'][i])}", expanded=False):
                st.session_state['meal_foods'][i] = st.multiselect(
                    f"Selecione os alimentos para {meal_name}",
                    options=all_food_names,
                    default=st.session_state['meal_foods'][i],
                    key=f'multiselect_{i}'
                )

        if st.button("Gerar Dieta Final em Gramas", type="primary"):
            run_optimization(targets, st.session_state['meal_foods'])


def run_optimization(targets, meal_foods):
    # Distribui a meta nutricional igualmente entre as refeições
    num_meals = targets['num_meals']
    meal_targets = {
        'cal': targets['cal'] / num_meals,
        'prot': targets['prot'] / num_meals,
        'carbs': targets['carbs'] / num_meals,
        'fat': targets['fat'] / num_meals,
    }

    final_plan = []
    total_opt_cal = 0
    optimization_failed = False

    # Itera sobre cada refeição e executa uma otimização separada
    for i, selected_foods in enumerate(meal_foods):
        if not selected_foods:
            final_plan.append({'Refeição': f"Refeição {i+1}", 'Alimento': 'Nenhum', 'Gramas': 0})
            continue

        # Filtra o DataFrame apenas com os alimentos selecionados para esta refeição
        df_meal = targets['df_foods'][targets['df_foods']['name'].isin(selected_foods)].set_index('name')
        
        if df_meal.empty: continue

        meal_foods_list = df_meal.index.tolist()
        
        # Variáveis de Decisão: Gramas de cada alimento (Contínua, não Inteira!)
        # Dividimos por 100 para converter de gramas para 100g (unidade do DB)
        food_vars = LpVariable.dicts(f"Gramas_Refeicao_{i+1}", meal_foods_list, 0, None, cat=const.LpContinuous)

        prob = LpProblem(f"Otimizacao_Refeicao_{i+1}", LpMinimize)
        
        # Variáveis de Desvio (Penalty)
        dev_cal_pos = LpVariable(f"Desvio_Cal_Pos_{i}", 0) 
        dev_cal_neg = LpVariable(f"Desvio_Cal_Neg_{i}", 0)

        # Restrição 1: Caloria Alvo
        prob += lpSum(df_meal.loc[r, 'calories'] / 100 * food_vars[r] for r in meal_foods_list) + dev_cal_neg - dev_cal_pos == meal_targets['cal'], f"Restricao_Calorias_{i}"
        
        # Função Objetivo: Minimizar os desvios
        prob += dev_cal_pos + dev_cal_neg, f"Minimizar_Desvio_Calorico_{i}"

        # Restrições de Nutrientes (95% Min, 110% Max)
        # Atenção à divisão por 100 para converter a unidade de 100g para 1g
        prob += lpSum(df_meal.loc[r, 'protein'] / 100 * food_vars[r] for r in meal_foods_list) >= meal_targets['prot'] * 0.95, f"Restricao_Proteina_Min_{i}"
        prob += lpSum(df_meal.loc[r, 'carbs'] / 100 * food_vars[r] for r in meal_foods_list) >= meal_targets['carbs'] * 0.95, f"Restricao_Carbos_Min_{i}"
        prob += lpSum(df_meal.loc[r, 'fat'] / 100 * food_vars[r] for r in meal_foods_list) <= meal_targets['fat'] * 1.1, f"Restricao_Gordura_Max_{i}"

        # Restrição de Tamanho Mínimo (Evitar 0g): Exige pelo menos 10g de um dos alimentos na refeição
        prob += lpSum(food_vars[r] for r in meal_foods_list) >= 10, f"Restricao_Minimo_Geral_{i}"
        
        prob.solve(PULP_CBC_CMD())
        
        if LpStatus[prob.status] == "Optimal":
            total_opt_cal += value(meal_targets['cal'] - dev_cal_neg + dev_cal_pos)
            
            for v in prob.variables():
                if v.varValue > 1 and f"Gramas_Refeicao_{i+1}" in v.name: # Filtra gramas > 1g
                    food_name = v.name.split('_')[-1].replace('_', ' ')
                    final_plan.append({
                        'Refeição': f"Refeição {i+1}",
                        'Alimento': food_name,
                        'Gramas': round(v.varValue, 1),
                    })
        else:
            optimization_failed = True
            st.error(f"❌ Otimização Falhou para **Refeição {i+1}**. Tente adicionar alimentos com mais variedade de macronutrientes ou revise suas metas.")
            return

    # --- 3. Resultado Final ---
    if not optimization_failed:
        st.subheader("3. Dieta Final Otimizada (Gramas por Refeição)")
        st.success("✅ Plano detalhado gerado com sucesso!")
        st.metric("Calorias Totais (Diárias)", f"{total_opt_cal:.0f} kcal")
        
        df_final = pd.DataFrame(final_plan)
        
        # Formata o DataFrame para exibição
        df_final = df_final.groupby(['Refeição', 'Alimento'])['Gramas'].sum().reset_index()
        df_final['Gramas'] = df_final['Gramas'].round(0).astype(int).astype(str) + ' g'
        
        st.dataframe(df_final, hide_index=True)


def page_receitas():
    st.header("🍚 Banco de Alimentos (Estilo TACO - 100g)")
    st.info("Cadastre os dados nutricionais de cada alimento para uma porção de **100g**.")

    # --- Formulário de Cadastro ---
    st.subheader("Adicionar Novo Alimento (Dados para 100g)")
    with st.form("nova_receita"):
        nome = st.text_input("Nome do Alimento (Ex: Arroz Cozido, Peito de Frango)")
        
        col1, col2 = st.columns(2)
        with col1:
            calorias = st.number_input("Calorias (kcal) / 100g", min_value=0)
            proteina = st.number_input("Proteína (g) / 100g", min_value=0.0, format="%.1f")
        with col2:
            carboidratos = st.number_input("Carbohidratos (g) / 100g", min_value=0.0, format="%.1f")
            gordura = st.number_input("Gordura (g) / 100g", min_value=0.0, format="%.1f")
        
        submitted = st.form_submit_button("Salvar Alimento", type="primary")
        if submitted and nome:
            if save_food(nome, calorias, proteina, carboidratos, gordura):
                st.success(f"Alimento '{nome}' (dados por 100g) salvo com sucesso!")
            else:
                st.error(f"Erro: O alimento '{nome}' já existe. Por favor, use um nome diferente.")
    
    st.markdown("---")

    # --- Visualização dos Alimentos Salvos ---
    st.subheader("Alimentos Cadastrados (por 100g)")
    df_foods = get_all_foods()
    if not df_foods.empty:
        df_foods.columns = ['ID', 'Nome', 'Custo (R$)', 'Calorias (kcal)/100g', 'Proteína (g)/100g', 'Carbohidratos (g)/100g', 'Gordura (g)/100g']
        st.dataframe(df_foods[['Nome', 'Calorias (kcal)/100g', 'Proteína (g)/100g', 'Carbohidratos (g)/100g', 'Gordura (g)/100g']], hide_index=True)
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
    ax.set_title('Distribuição Total de Macronutrientes (Por 100g de Alimento)')
    
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

    st.sidebar.title("EveFii v5 Completo (Nutrição)")
    selection = st.sidebar.radio("Navegação", list(PAGES.keys()))
    
    st.sidebar.markdown("---")
    if st.sidebar.button("Logout", type="secondary"):
        st.session_state['logged_in'] = False
        st.session_state.pop('username', None)
        st.rerun()

    PAGES[selection]()

def show_login():
    st.title("EveFii v5 — Focado em Nutrição")
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
    
    st.set_page_config(page_title="EveFii v5 Nutrição", layout="wide")
    
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
