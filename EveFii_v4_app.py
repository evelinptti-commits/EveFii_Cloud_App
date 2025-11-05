# EveFii_v6_app.py - Versão FINAL (Foco em Gramas, Refeições, Edição/Exclusão - SEM INVENTÁRIO)

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

# 2. Inicialização do Banco de Dados (Tabela 'inventory' removida)
@st.cache_resource
def init_db():
    conn = get_conn(); cur = conn.cursor()
    
    cur.execute('CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE, password_hash TEXT)')
    
    # Tabela de Alimentos (Nutrientes para 100g)
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
    
    # Adiciona usuário padrão se o banco estiver vazio
    cur.execute("SELECT COUNT(*) FROM users"); c = cur.fetchone()[0]
    if c == 0:
        pw = hashlib.sha256('change-me'.encode()).hexdigest()
        cur.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)", ('eve', pw))
    
    conn.commit()
    conn.close()

# 3. Funções de Criptografia e Verificação (Inalteradas)
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

# 4. Funções de Alimentos (CRUDS - Adição de Edição e Exclusão)
def save_food(name, cal, prot, carb, fat):
    conn = get_conn(); cur = conn.cursor()
    try:
        # Custo é sempre 0.0, pois o foco é em nutrição e não custo
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
    # Seleciona o ID para uso na edição/exclusão
    foods = pd.read_sql("SELECT id, name, cost, calories, protein, carbs, fat FROM recipes", conn)
    conn.close()
    return foods

def get_food_by_id(food_id):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT id, name, calories, protein, carbs, fat FROM recipes WHERE id=?", (food_id,))
    food = cur.fetchone()
    conn.close()
    return dict(food) if food else None

def update_food(food_id, name, cal, prot, carb, fat):
    conn = get_conn(); cur = conn.cursor()
    try:
        cur.execute("UPDATE recipes SET name=?, calories=?, protein=?, carbs=?, fat=? WHERE id=?", 
                    (name, cal, prot, carb, fat, food_id))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        # Integridade pode falhar se o novo nome já existir
        return False
    finally:
        conn.close()

def delete_food(food_id):
    conn = get_conn(); cur = conn.cursor()
    try:
        cur.execute("DELETE FROM recipes WHERE id=?", (food_id,))
        conn.commit()
        return True
    except Exception:
        return False
    finally:
        conn.close()

# --- Cálculo da TMB e Macros (LÓGICA INTELIGENTE) - Inalterada ---

def calculate_smart_macros(gender, weight, height, age, activity_level_factor, goal):
    # 1. Cálculo do TMB (Mifflin-St Jeor)
    if gender == 'Masculino':
        tmb = (10 * weight) + (6.25 * height) - (5 * age) + 5
    else: # Feminino
        tmb = (10 * weight) + (6.25 * height) - (5 * age) - 161
        
    get_tdee = tmb * activity_level_factor
    
    # 2. Ajuste de Calorias (GET Final) e Multiplicador de Proteína
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

# --- LÓGICA DE OTIMIZAÇÃO POR REFEIÇÃO (Inalterada) ---

def run_optimization(targets, meal_foods):
    num_meals = targets['num_meals']
    
    # Distribui metas por refeição
    meal_targets = {
        'cal': targets['cal'] / num_meals,
        'prot': targets['prot'] / num_meals,
        'carbs': targets['carbs'] / num_meals,
        'fat': targets['fat'] / num_meals,
    }

    final_plan = []
    total_opt_cal = 0
    optimization_failed = False

    for i, selected_foods in enumerate(meal_foods):
        if not selected_foods:
            # Garante que refeições vazias sejam consideradas no total de calorias
            final_plan.append({'Refeição': f"Refeição {i+1}", 'Alimento': 'Nenhum', 'Gramas': 0})
            continue

        df_meal = targets['df_foods'][targets['df_foods']['name'].isin(selected_foods)].set_index('name')
        
        if df_meal.empty: continue

        meal_foods_list = df_meal.index.tolist()
        
        # Variáveis de Decisão: Gramas de cada alimento (Contínua)
        food_vars = LpVariable.dicts(f"Gramas_Refeicao_{i+1}", meal_foods_list, 0, None, cat=const.LpContinuous)

        prob = LpProblem(f"Otimizacao_Refeicao_{i+1}", LpMinimize)
        
        dev_cal_pos = LpVariable(f"Desvio_Cal_Pos_{i}", 0) 
        dev_cal_neg = LpVariable(f"Desvio_Cal_Neg_{i}", 0)

        # Restrição de Calorias
        prob += lpSum(df_meal.loc[r, 'calories'] / 100 * food_vars[r] for r in meal_foods_list) + dev_cal_neg - dev_cal_pos == meal_targets['cal'], f"Restricao_Calorias_{i}"
        
        prob += dev_cal_pos + dev_cal_neg, f"Minimizar_Desvio_Calorico_{i}"

        # Restrições de Nutrientes (95% Min, 110% Max)
        prob += lpSum(df_meal.loc[r, 'protein'] / 100 * food_vars[r] for r in meal_foods_list) >= meal_targets['prot'] * 0.95, f"Restricao_Proteina_Min_{i}"
        prob += lpSum(df_meal.loc[r, 'carbs'] / 100 * food_vars[r] for r in meal_foods_list) >= meal_targets['carbs'] * 0.95, f"Restricao_Carbos_Min_{i}"
        prob += lpSum(df_meal.loc[r, 'fat'] / 100 * food_vars[r] for r in meal_foods_list) <= meal_targets['fat'] * 1.1, f"Restricao_Gordura_Max_{i}"

        # Restrição de Tamanho Mínimo (Evitar 0g)
        prob += lpSum(food_vars[r] for r in meal_foods_list) >= 10, f"Restricao_Minimo_Geral_{i}"
        
        prob.solve(PULP_CBC_CMD())
        
        if LpStatus[prob.status] == "Optimal":
            total_opt_cal += value(meal_targets['cal'] - dev_cal_neg + dev_cal_pos)
            
            for v in prob.variables():
                if v.varValue > 1 and f"Gramas_Refeicao_{i+1}" in v.name:
                    food_name = v.name.split('_')[-1].replace('_', ' ')
                    final_plan.append({
                        'Refeição': f"Refeição {i+1}",
                        'Alimento': food_name,
                        'Gramas': round(v.varValue, 1),
                    })
        else:
            optimization_failed = True
            st.error(f"❌ Otimização Falhou para **Refeição {i+1}**. Não foi possível atingir as metas com os alimentos selecionados.")
            return

    # --- 3. Resultado Final ---
    if not optimization_failed:
        st.subheader("3. Dieta Final Otimizada (Gramas por Refeição)")
        st.success("✅ Plano detalhado gerado com sucesso!")
        
        df_final = pd.DataFrame(final_plan)
        
        # Calcula macros totais para exibição
        total_prot = df_final.apply(lambda row: targets['df_foods'][targets['df_foods']['name'] == row['Alimento'].replace(' ', '_')]['protein'].iloc[0] * (row['Gramas'] / 100) if not df_final.empty else 0, axis=1).sum()
        total_carbs = df_final.apply(lambda row: targets['df_foods'][targets['df_foods']['name'] == row['Alimento'].replace(' ', '_')]['carbs'].iloc[0] * (row['Gramas'] / 100) if not df_final.empty else 0, axis=1).sum()
        total_fat = df_final.apply(lambda row: targets['df_foods'][targets['df_foods']['name'] == row['Alimento'].replace(' ', '_')]['fat'].iloc[0] * (row['Gramas'] / 100) if not df_final.empty else 0, axis=1).sum()

        col_c, col_p, col_ca, col_g = st.columns(4)
        col_c.metric("Calorias Totais", f"{total_opt_cal:.0f} kcal")
        col_p.metric("Proteína Total", f"{total_prot:.1f} g")
        col_ca.metric("Carboidratos Totais", f"{total_carbs:.1f} g")
        col_g.metric("Gordura Total", f"{total_fat:.1f} g")
        
        # Formata o DataFrame para exibição
        df_final = df_final.groupby(['Refeição', 'Alimento'])['Gramas'].sum().reset_index()
        df_final['Gramas'] = df_final['Gramas'].round(0).astype(int).astype(str) + ' g'
        
        st.dataframe(df_final, hide_index=True)


# --- Estrutura das Páginas ---

def page_planejador_inteligente():
    st.header("🧠 Planejador Inteligente (Refeições e Gramas)")
    st.info("Otimize seu plano de alimentos em **gramas** para atingir as metas calculadas.")
    
    df_foods = get_all_foods()
    
    if df_foods.empty:
        st.warning("🚨 Por favor, cadastre alimentos na página 'Banco de Alimentos (TACO)' antes de otimizar.")
        return

    # --- 1. Cálculo de Metas ---
    st.subheader("1. Seus Dados e Objetivo")
    
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
        
        st.subheader("Suas Metas Diárias Calculadas:")
        col_c, col_p, col_ca, col_g = st.columns(4)
        col_c.metric("Calorias Alvo", f"{target_cal} kcal")
        col_p.metric("Proteína Alvo", f"{target_prot} g")
        col_ca.metric("Carboidratos Alvo", f"{target_carbs} g")
        col_g.metric("Gordura Alvo", f"{target_fat} g")
        st.markdown("---")
    
    
    # --- 2. Definição da Dieta por Refeição ---

    if 'targets' in st.session_state:
        targets = st.session_state['targets']
        
        st.subheader(f"2. Montagem do Plano de Refeições ({targets['num_meals']} Refeições)")
        st.info("Selecione os alimentos disponíveis para cada refeição.")

        if 'meal_foods' not in st.session_state or len(st.session_state['meal_foods']) != targets['num_meals']:
            st.session_state['meal_foods'] = [[] for _ in range(targets['num_meals'])]

        meal_names = [f"Refeição {i+1}" for i in range(targets['num_meals'])]
        all_food_names = targets['df_foods']['name'].tolist()
        
        # Interface de seleção de alimentos
        with st.container():
            for i, meal_name in enumerate(meal_names):
                st.session_state['meal_foods'][i] = st.multiselect(
                    f"🍽️ **{meal_name}** - Selecione Alimentos",
                    options=all_food_names,
                    default=st.session_state['meal_foods'][i],
                    key=f'multiselect_{i}'
                )

            st.markdown("---")
            if st.button("Gerar Dieta Final em Gramas", type="primary"):
                run_optimization(targets, st.session_state['meal_foods'])


def page_receitas():
    st.header("🍚 Banco de Alimentos (TACO) - 100g")
    st.info("Cadastre/Edite os dados nutricionais de cada alimento para uma porção de **100g**.")

    df_foods = get_all_foods()
    
    # --- 1. Visualização e Seleção para Edição ---
    st.subheader("Alimentos Cadastrados (por 100g)")
    if not df_foods.empty:
        # Renomeia as colunas para melhor visualização (inclui ID para seleção)
        df_display = df_foods.copy()
        df_display.columns = ['ID', 'Nome', 'Custo (R$)', 'Calorias (kcal)/100g', 'Proteína (g)/100g', 'Carbohidratos (g)/100g', 'Gordura (g)/100g']
        
        st.dataframe(df_display[['ID', 'Nome', 'Calorias (kcal)/100g', 'Proteína (g)/100g', 'Carbohidratos (g)/100g', 'Gordura (g)/100g']], hide_index=True)
        
        # Seleção para Edição/Exclusão
        st.markdown("---")
        st.subheader("Editar ou Excluir Alimento")
        
        food_id_to_edit = st.selectbox(
            "Selecione o ID do alimento para editar/excluir", 
            options=[None] + df_foods['id'].tolist(),
            format_func=lambda x: f"ID: {x} - {df_foods[df_foods['id'] == x]['name'].iloc[0]}" if x else "Selecione um ID"
        )

        if food_id_to_edit:
            food_to_edit = get_food_by_id(food_id_to_edit)
            
            with st.form("edita_alimento"):
                st.markdown(f"#### Editando: {food_to_edit['name']}")
                
                nome = st.text_input("Novo Nome do Alimento", value=food_to_edit['name'])
                
                col1, col2 = st.columns(2)
                with col1:
                    calorias = st.number_input("Calorias (kcal) / 100g", min_value=0, value=food_to_edit['calories'])
                    proteina = st.number_input("Proteína (g) / 100g", min_value=0.0, format="%.1f", value=food_to_edit['protein'])
                with col2:
                    carboidratos = st.number_input("Carbohidratos (g) / 100g", min_value=0.0, format="%.1f", value=food_to_edit['carbs'])
                    gordura = st.number_input("Gordura (g) / 100g", min_value=0.0, format="%.1f", value=food_to_edit['fat'])
                
                col_save, col_delete = st.columns([1,1])
                with col_save:
                    submitted_edit = st.form_submit_button("Atualizar Alimento", type="primary")
                with col_delete:
                    if st.form_submit_button("Excluir Alimento", type="secondary"):
                        if delete_food(food_id_to_edit):
                            st.success(f"Alimento '{food_to_edit['name']}' excluído.")
                            st.session_state['refresh_foods'] = True
                            st.rerun()
                        else:
                            st.error("Erro ao excluir alimento.")

                if submitted_edit:
                    if update_food(food_id_to_edit, nome, calorias, proteina, carboidratos, gordura):
                        st.success(f"Alimento '{nome}' atualizado com sucesso!")
                        st.session_state['refresh_foods'] = True
                        st.rerun()
                    else:
                        st.error(f"Erro: Não foi possível atualizar. O nome '{nome}' pode já existir.")

    else:
        st.info("Nenhum alimento cadastrado ainda.")
    
    st.markdown("---")

    # --- 2. Formulário de Cadastro (Novo Alimento) ---
    st.subheader("Adicionar Novo Alimento")
    with st.form("nova_receita"):
        nome = st.text_input("Nome do Alimento (Ex: Arroz Cozido)")
        
        col1, col2 = st.columns(2)
        with col1:
            calorias = st.number_input("Calorias (kcal) / 100g", min_value=0)
            proteina = st.number_input("Proteína (g) / 100g", min_value=0.0, format="%.1f")
        with col2:
            carboidratos = st.number_input("Carbohidratos (g) / 100g", min_value=0.0, format="%.1f")
            gordura = st.number_input("Gordura (g) / 100g", min_value=0.0, format="%.1f")
        
        submitted = st.form_submit_button("Salvar Novo Alimento", type="primary")
        if submitted and nome:
            if save_food(nome, calorias, proteina, carboidratos, gordura):
                st.success(f"Alimento '{nome}' salvo com sucesso!")
                st.session_state['refresh_foods'] = True
                st.rerun()
            else:
                st.error(f"Erro: O alimento '{nome}' já existe. Por favor, use um nome diferente.")

# A página de inventário foi removida.
def page_relatorios():
    st.header("📊 Relatórios e Análise de Nutrientes")
    st.info("Gráfico de análise da composição dos alimentos cadastrados.")
    
    st.subheader("Distribuição de Nutrientes Cadastrados")
    
    df_foods = get_all_foods()
    
    if df_foods.empty:
        st.warning("Cadastre alimentos para visualizar a análise.")
        return

    total_prot = df_foods['protein'].sum()
    total_carbs = df_foods['carbs'].sum()
    total_fat = df_foods['fat'].sum()
    
    data = [total_prot, total_carbs, total_fat]
    labels = ['Proteína', 'Carboidratos', 'Gordura']
    
    fig, ax = plt.subplots()
    ax.pie(data, labels=labels, autopct='%1.1f%%', startangle=90, colors=['#4CAF50', '#2196F3', '#FFC107'])
    ax.axis('equal') 
    ax.set_title('Distribuição Total de Macronutrientes (Por 100g de Alimento)')
    
    st.pyplot(fig)


# --- Login e Roteamento Principal ---

def main_app():
    # Exibe o usuário logado na sidebar
    st.sidebar.markdown(f"**Usuário Logado:** `{st.session_state.get('username', 'N/A')}`")
    st.sidebar.markdown("---")
    
    # Dicionário de páginas: 'Inventário' removido
    PAGES = {
        "Planejador Inteligente": page_planejador_inteligente,
        "Banco de Alimentos (TACO)": page_receitas, 
        "Relatórios": page_relatorios
    }

    st.sidebar.title("EveFii v6 Completo (Nutrição)")
    selection = st.sidebar.radio("Navegação", list(PAGES.keys()))
    
    st.sidebar.markdown("---")
    if st.sidebar.button("Logout", type="secondary"):
        st.session_state['logged_in'] = False
        st.session_state.pop('username', None)
        st.rerun()

    PAGES[selection]()

def show_login():
    st.title("EveFii v6 — Focado em Nutrição")
    st.subheader("Faça Login para Continuar")
    
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
    
    st.set_page_config(page_title="EveFii v6 Nutrição", layout="wide")
    
    init_db()
    
    os.makedirs(PHOTOS_DIR, exist_ok=True)
    
    if 'logged_in' not in st.session_state:
        st.session_state['logged_in'] = False

    if st.session_state['logged_in']:
        main_app()
    else:
        show_login()
