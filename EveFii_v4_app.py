# EveFii_v11_app.py - Versão Multiusuário e Completa

# Imports
import streamlit as st
import sqlite3
import hashlib
import os
import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime
from pulp import LpProblem, LpMinimize, LpVariable, PULP_CBC_CMD, LpStatus, value, lpSum, const
import math

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

# NOVO: Funções de Usuário para obter o ID
def get_user_id(username):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT id FROM users WHERE username = ?", (username,))
    user = cur.fetchone()
    conn.close()
    return user['id'] if user else None

# 2. Inicialização do Banco de Dados (Com Correção de Migração)
@st.cache_resource
def init_db():
    conn = get_conn(); cur = conn.cursor()
    
    # 1. Tabela de Usuários (Mantida)
    cur.execute('CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE, password_hash TEXT)')
    
    # 2. Tabela de Alimentos (Adicionando user_id)
    cur.execute('''
        CREATE TABLE IF NOT EXISTS recipes (
            id INTEGER PRIMARY KEY AUTOINCREMENT, 
            user_id INTEGER, -- NOVO
            name TEXT, 
            cost REAL, 
            calories INTEGER, 
            protein REAL, 
            carbs REAL, 
            fat REAL
        )
    ''')
    
    # 3. Tabela de Métricas Corporais (Adicionando user_id)
    cur.execute('''
        CREATE TABLE IF NOT EXISTS body_metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT, 
            user_id INTEGER, -- NOVO
            date TEXT, 
            weight REAL, 
            body_fat_perc REAL,
            waist_circ REAL,
            bmi REAL
        )
    ''')
    
    # --- CORREÇÕES DE MIGRAÇÃO (Multi-step) ---
    
    # Correção 1: Adicionar BMI se estiver faltando (de v9 para v10)
    try:
        cur.execute("SELECT bmi FROM body_metrics LIMIT 1")
    except sqlite3.OperationalError:
        cur.execute("ALTER TABLE body_metrics ADD COLUMN bmi REAL")
        
    # Correção 2: Adicionar user_id nas tabelas (de v10 para v11)
    # Assumimos que dados antigos pertencem ao usuário 'eve' (ID 1), se ele existir.
    
    # Tentativa de adicionar 'user_id' em body_metrics
    try:
        cur.execute("SELECT user_id FROM body_metrics LIMIT 1")
    except sqlite3.OperationalError:
        cur.execute("ALTER TABLE body_metrics ADD COLUMN user_id INTEGER")
        # Se a coluna foi adicionada, preenche dados antigos com user_id=1 (eve)
        cur.execute("UPDATE body_metrics SET user_id = 1 WHERE user_id IS NULL")

    # Tentativa de adicionar 'user_id' em recipes
    try:
        cur.execute("SELECT user_id FROM recipes LIMIT 1")
    except sqlite3.OperationalError:
        cur.execute("ALTER TABLE recipes ADD COLUMN user_id INTEGER")
        # Se a coluna foi adicionada, preenche dados antigos com user_id=1 (eve)
        cur.execute("UPDATE recipes SET user_id = 1 WHERE user_id IS NULL")
        
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
    
# NOVO: Função para registrar novo usuário (permite que a esposa se cadastre)
def register_user(username, password):
    conn = get_conn(); cur = conn.cursor()
    try:
        password_hash = hash_password(password)
        cur.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)", (username, password_hash))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

# 4. Funções de Alimentos (CRUDS - AGORA FILTRADAS POR user_id)
def save_food(user_id, name, cal, prot, carb, fat):
    conn = get_conn(); cur = conn.cursor()
    try:
        # A restrição UNIQUE agora é por (user_id, name)
        cur.execute("INSERT INTO recipes (user_id, name, cost, calories, protein, carbs, fat) VALUES (?, ?, 0.0, ?, ?, ?, ?)", 
                    (user_id, name, cal, prot, carb, fat))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def get_all_foods(user_id):
    conn = get_conn(); 
    # Filtra por user_id
    foods = pd.read_sql("SELECT id, name, cost, calories, protein, carbs, fat FROM recipes WHERE user_id = ?", conn, params=(user_id,))
    conn.close()
    return foods

def get_food_by_id(food_id): # Não precisa de user_id aqui, pois o ID é único.
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT id, name, calories, protein, carbs, fat FROM recipes WHERE id=?", (food_id,))
    food = cur.fetchone()
    conn.close()
    return dict(food) if food else None

def update_food(food_id, name, cal, prot, carb, fat):
    conn = get_conn(); cur = conn.cursor()
    try:
        # Nota: A atualização só é feita se o ID existir e o nome não colidir no mesmo user_id.
        cur.execute("UPDATE recipes SET name=?, calories=?, protein=?, carbs=?, fat=? WHERE id=?", 
                    (name, cal, prot, carb, fat, food_id))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
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
        
# 5. Funções de Métricas Corporais (FILTRADAS POR user_id)

# FÓRMULAS DE CÁLCULO (Inalteradas)
def calculate_body_fat_navy(gender, height, neck, waist, hip=0):
    # ... [Código da fórmula Naval inalterado] ...
    h_in = height * 0.3937; n_in = neck * 0.3937; w_in = waist * 0.3937; hip_in = hip * 0.3937
    if gender == 'Masculino':
        try:
            bf = 495 / (1.0324 - 0.19077 * math.log10(w_in - n_in) + 0.15456 * math.log10(h_in)) - 450
        except ValueError: bf = 5.0
    else:
        try:
            bf = 495 / (1.29579 - 0.35004 * math.log10(w_in + hip_in - n_in) + 0.22100 * math.log10(h_in)) - 450
        except ValueError: bf = 10.0 
    return max(5.0, min(50.0, bf))

def calculate_body_fat_jp7(gender, age, sk_chest, sk_triceps, sk_subscap, sk_midax, sk_supra, sk_abdomen, sk_thigh):
    # ... [Código da fórmula JP7 inalterado] ...
    S7SKF = sk_chest + sk_triceps + sk_subscap + sk_midax + sk_supra + sk_abdomen + sk_thigh
    if S7SKF <= 0: return 5.0 
    try:
        if gender == 'Masculino':
            DB = 1.112 - (0.00043499 * S7SKF) + (0.00000055 * S7SKF**2) - (0.00028826 * age)
        else: 
            DB = 1.0970 - (0.00046971 * S7SKF) + (0.00000056 * S7SKF**2) - (0.00012828 * age)
        bf = (495 / DB) - 450
    except Exception:
        bf = 5.0 
    return max(5.0, min(50.0, bf))

def calculate_bmi(weight, height):
    height_m = height / 100.0
    if height_m <= 0: return 0.0
    return weight / (height_m ** 2)
# FIM FÓRMULAS DE CÁLCULO

def save_body_metric(user_id, date, weight, body_fat_perc, waist_circ, bmi):
    conn = get_conn(); cur = conn.cursor()
    try:
        # Salva com o user_id
        cur.execute("INSERT INTO body_metrics (user_id, date, weight, body_fat_perc, waist_circ, bmi) VALUES (?, ?, ?, ?, ?, ?)", 
                    (user_id, date, weight, body_fat_perc, waist_circ, bmi))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def get_body_metrics(user_id):
    conn = get_conn(); 
    # Filtra por user_id
    metrics = pd.read_sql("SELECT date, weight, body_fat_perc, waist_circ, bmi FROM body_metrics WHERE user_id = ? ORDER BY date DESC", conn, params=(user_id,))
    conn.close()
    
    if metrics.empty:
        return metrics
        
    # Cálculo da Massa Gorda (Peso Gordo) e Massa Magra (Peso Magro)
    metrics['date'] = pd.to_datetime(metrics['date'])
    metrics['Massa Gorda (kg)'] = metrics['weight'] * (metrics['body_fat_perc'] / 100)
    metrics['Massa Magra (kg)'] = metrics['weight'] - metrics['Massa Gorda (kg)']
    
    return metrics

# --- Funções de Planejador e Receitas (Adaptadas) ---

def calculate_smart_macros(gender, weight, height, age, activity_level_factor, goal):
    # [Cálculo de TMB e Metas inalterado]
    if gender == 'Masculino': tmb = (10 * weight) + (6.25 * height) - (5 * age) + 5
    else: tmb = (10 * weight) + (6.25 * height) - (5 * age) - 161
        
    get_tdee = tmb * activity_level_factor
    
    if goal == 'Déficit Calórico':
        final_cal = get_tdee - 500; final_cal = max(final_cal, 1200); prot_multiplier = 2.0; fat_perc = 0.20
    elif goal == 'Hipertrofia Muscular':
        final_cal = get_tdee + 300; prot_multiplier = 2.2; fat_perc = 0.25
    else:
        final_cal = get_tdee; prot_multiplier = 1.8; fat_perc = 0.25

    final_cal = int(final_cal); target_prot = int(weight * prot_multiplier) 
    target_fat = int((final_cal * fat_perc) / 9) 
    cal_from_prot_fat = (target_prot * 4) + (target_fat * 9) 
    cal_from_carbs = max(final_cal - cal_from_prot_fat, 400) 
    target_carbs = int(cal_from_carbs / 4)
    
    return int(final_cal), target_prot, target_carbs, target_fat

# Run Optimization inalterada, depende apenas do DF filtrado

# --- Estrutura das Páginas ---

def page_planejador_inteligente():
    user_id = st.session_state['user_id']
    st.header("🧠 Planejador Inteligente (Refeições e Gramas)")
    st.info("Otimize seu plano de alimentos em **gramas** para atingir as metas calculadas.")
    
    # Busca alimentos APENAS do usuário logado
    df_foods = get_all_foods(user_id) 
    
    if df_foods.empty:
        st.warning(f"🚨 Por favor, **{st.session_state['username']}**, cadastre alimentos na página 'Banco de Alimentos (TACO)' antes de otimizar.")
        return

    # --- 1. Cálculo de Metas ---
    st.subheader("1. Seus Dados e Objetivo")
    with st.form("metas_calc_form"):
        # [Formulário de Cálculo inalterado]
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
    
    # --- 2. Definição da Dieta por Refeição (Inalterada) ---
    if 'targets' in st.session_state:
        targets = st.session_state['targets']
        st.subheader(f"2. Montagem do Plano de Refeições ({targets['num_meals']} Refeições)")
        # [Lógica de Otimização e UI inalterada]
        # ... (Mantendo o código run_optimization e a UI da página)

        if 'meal_foods' not in st.session_state or len(st.session_state['meal_foods']) != targets['num_meals']:
            st.session_state['meal_foods'] = [[] for _ in range(targets['num_meals'])]
        if 'meal_names' not in st.session_state or len(st.session_state['meal_names']) != targets['num_meals']:
            st.session_state['meal_names'] = [f"Refeição {i+1}" for i in range(targets['num_meals'])]

        all_food_names = targets['df_foods']['name'].tolist()
        st.markdown("##### Personalize os Nomes e Selecione os Alimentos:")
        
        meal_cols = st.columns(targets['num_meals'])
        
        for i in range(targets['num_meals']):
            with meal_cols[i]:
                st.session_state['meal_names'][i] = st.text_input(
                    f"Nome da Refeição {i+1}", 
                    value=st.session_state['meal_names'][i], 
                    key=f'meal_name_{i}'
                )
                st.session_state['meal_foods'][i] = st.multiselect(
                    f"Alimentos para {st.session_state['meal_names'][i]}",
                    options=all_food_names,
                    default=st.session_state['meal_foods'][i],
                    key=f'multiselect_{i}'
                )
        
        st.markdown("---")
        if st.button("Gerar Dieta Final em Gramas", type="primary"):
            # A função run_optimization deve ser definida aqui ou importada. 
            # Reutilizando o corpo da função run_optimization da v10/v9, se necessário.
            run_optimization(targets, st.session_state['meal_foods'], st.session_state['meal_names'])

# Re-implementação da função run_optimization para manter o código autônomo
def run_optimization(targets, meal_foods, meal_names):
    num_meals = targets['num_meals']
    meal_targets = {
        'cal': targets['cal'] / num_meals, 'prot': targets['prot'] / num_meals,
        'carbs': targets['carbs'] / num_meals, 'fat': targets['fat'] / num_meals,
    }
    final_plan = []; total_opt_cal = 0; optimization_failed = False

    for i, selected_foods in enumerate(meal_foods):
        meal_name = meal_names[i]
        if not selected_foods:
            final_plan.append({'Refeição': meal_name, 'Alimento': 'Nenhum', 'Gramas': 0})
            continue

        df_meal = targets['df_foods'][targets['df_foods']['name'].isin(selected_foods)].set_index('name')
        if df_meal.empty: continue
        meal_foods_list = df_meal.index.tolist()
        food_vars = LpVariable.dicts(f"Gramas_Refeicao_{i+1}", meal_foods_list, 0, None, cat=const.LpContinuous)
        prob = LpProblem(f"Otimizacao_Refeicao_{i+1}", LpMinimize)
        dev_cal_pos = LpVariable(f"Desvio_Cal_Pos_{i}", 0); dev_cal_neg = LpVariable(f"Desvio_Cal_Neg_{i}", 0)

        prob += lpSum(df_meal.loc[r, 'calories'] / 100 * food_vars[r] for r in meal_foods_list) + dev_cal_neg - dev_cal_pos == meal_targets['cal'], f"Restricao_Calorias_{i}"
        prob += dev_cal_pos + dev_cal_neg, f"Minimizar_Desvio_Calorico_{i}"
        prob += lpSum(df_meal.loc[r, 'protein'] / 100 * food_vars[r] for r in meal_foods_list) >= meal_targets['prot'] * 0.95, f"Restricao_Proteina_Min_{i}"
        prob += lpSum(df_meal.loc[r, 'carbs'] / 100 * food_vars[r] for r in meal_foods_list) >= meal_targets['carbs'] * 0.95, f"Restricao_Carbos_Min_{i}"
        prob += lpSum(df_meal.loc[r, 'fat'] / 100 * food_vars[r] for r in meal_foods_list) <= meal_targets['fat'] * 1.1, f"Restricao_Gordura_Max_{i}"
        prob += lpSum(food_vars[r] for r in meal_foods_list) >= 10, f"Restricao_Minimo_Geral_{i}"
        
        prob.solve(PULP_CBC_CMD())
        
        if LpStatus[prob.status] == "Optimal":
            total_opt_cal += value(meal_targets['cal'] - dev_cal_neg + dev_cal_pos)
            for v in prob.variables():
                if v.varValue > 1 and f"Gramas_Refeicao_{i+1}" in v.name:
                    food_name = v.name.split('_')[-1].replace('_', ' ')
                    final_plan.append({'Refeição': meal_name, 'Alimento': food_name, 'Gramas': round(v.varValue, 1)})
        else:
            optimization_failed = True
            st.error(f"❌ Otimização Falhou para **{meal_name}**.")
            return

    if not optimization_failed:
        st.subheader("3. Dieta Final Otimizada (Gramas por Refeição)")
        st.success("✅ Plano detalhado gerado com sucesso!")
        df_final = pd.DataFrame(final_plan)
        df_foods_lookup = targets['df_foods'].set_index('name')
        
        total_prot = df_final.apply(lambda row: df_foods_lookup.loc[row['Alimento'].replace(' ', '_'), 'protein'] * (row['Gramas'] / 100) if row['Alimento'] != 'Nenhum' and row['Alimento'].replace(' ', '_') in df_foods_lookup.index else 0, axis=1).sum()
        total_carbs = df_final.apply(lambda row: df_foods_lookup.loc[row['Alimento'].replace(' ', '_'), 'carbs'] * (row['Gramas'] / 100) if row['Alimento'] != 'Nenhum' and row['Alimento'].replace(' ', '_') in df_foods_lookup.index else 0, axis=1).sum()
        total_fat = df_final.apply(lambda row: df_foods_lookup.loc[row['Alimento'].replace(' ', '_'), 'fat'] * (row['Gramas'] / 100) if row['Alimento'] != 'Nenhum' and row['Alimento'].replace(' ', '_') in df_foods_lookup.index else 0, axis=1).sum()

        col_c, col_p, col_ca, col_g = st.columns(4)
        col_c.metric("Calorias Totais", f"{total_opt_cal:.0f} kcal")
        col_p.metric("Proteína Total", f"{total_prot:.1f} g")
        col_ca.metric("Carboidratos Totais", f"{total_carbs:.1f} g")
        col_g.metric("Gordura Total", f"{total_fat:.1f} g")
        
        df_final = df_final.groupby(['Refeição', 'Alimento'])['Gramas'].sum().reset_index()
        df_final['Gramas'] = df_final['Gramas'].round(0).astype(int).astype(str) + ' g'
        st.dataframe(df_final, hide_index=True)


def page_receitas():
    user_id = st.session_state['user_id']
    st.header("🍚 Banco de Alimentos (TACO) - 100g")
    st.info(f"Gerencie seu banco de alimentos, **{st.session_state['username']}**.")
    
    # Busca alimentos APENAS do usuário logado
    df_foods = get_all_foods(user_id) 
    
    st.subheader("Alimentos Cadastrados (por 100g)")
    if not df_foods.empty:
        # [Visualização de Alimentos e Edição Inalterada]
        df_display = df_foods.copy()
        df_display.columns = ['ID', 'Nome', 'Custo (R$)', 'Calorias (kcal)/100g', 'Proteína (g)/100g', 'Carbohidratos (g)/100g', 'Gordura (g)/100g']
        st.dataframe(df_display[['ID', 'Nome', 'Calorias (kcal)/100g', 'Proteína (g)/100g', 'Carbohidratos (g)/100g', 'Gordura (g)/100g']], hide_index=True)
        
        st.markdown("---")
        st.subheader("Editar ou Excluir Alimento")
        
        food_options = {id_: name for id_, name in zip(df_foods['id'], df_foods['name'])}
        food_id_to_edit = st.selectbox(
            "Selecione o ID do alimento para editar/excluir", 
            options=[None] + list(food_options.keys()),
            format_func=lambda x: f"ID: {x} - {food_options[x]}" if x else "Selecione um ID"
        )

        if food_id_to_edit:
            food_to_edit = get_food_by_id(food_id_to_edit) # get_food_by_id não precisa de user_id
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
                            st.rerun()
                         else:
                            st.error("Erro ao excluir alimento.")

                if submitted_edit:
                    if update_food(food_id_to_edit, nome, calorias, proteina, carboidratos, gordura):
                        st.success(f"Alimento '{nome}' atualizado com sucesso!")
                        st.rerun()
                    else:
                        st.error(f"Erro: Não foi possível atualizar. O nome '{nome}' pode já existir para você.")
    else:
        st.info("Nenhum alimento cadastrado ainda.")
    
    st.markdown("---")

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
            # Salva o alimento associado ao user_id
            if save_food(user_id, nome, calorias, proteina, carboidratos, gordura):
                st.success(f"Alimento '{nome}' salvo com sucesso!")
                st.rerun()
            else:
                st.error(f"Erro: O alimento '{nome}' já existe para você. Por favor, use um nome diferente.")

def page_avaliacao_fisica():
    user_id = st.session_state['user_id']
    st.header(f"🏋️ Avaliação Física e Composição Corporal - {st.session_state['username']}")
    st.info("Monitore sua composição corporal separadamente.")
    
    # --- 1. Formulário de Cálculo e Cadastro de Métrica ---
    st.subheader("Registrar Nova Métrica")
    
    initial_values = {
        'weight': 75.0, 'height': 175.0, 'age': 30, 'neck': 38.0, 'waist': 80.0, 'hip': 95.0,
        'sk_chest': 10.0, 'sk_triceps': 10.0, 'sk_subscap': 15.0, 'sk_midax': 10.0, 'sk_supra': 15.0, 'sk_abdomen': 20.0, 'sk_thigh': 20.0
    }
    
    # Busca métricas APENAS do usuário logado
    df_metrics = get_body_metrics(user_id) 
    
    if not df_metrics.empty:
        last = df_metrics.iloc[0]
        initial_values['weight'] = last['weight']
        initial_values['waist'] = last['waist_circ']

    calculated_bf = None
    
    with st.form("new_metric"):
        date = st.date_input("Data da Avaliação", value=datetime.today())
        
        col_dados, col_medidas = st.columns(2)
        
        with col_dados:
            # [Dados Pessoais Inalterados]
            gender = st.selectbox("Gênero", ['Masculino', 'Feminino'], key='eval_gender')
            weight = st.number_input("Peso (kg)", min_value=30.0, format="%.1f", value=initial_values['weight'])
            height = st.number_input("Altura (cm)", min_value=100.0, format="%.1f", value=initial_values['height'])
            age = st.number_input("Idade (anos)", min_value=15, value=initial_values['age'])
            
            calc_method = st.radio(
                "Método de Cálculo de % Gordura", 
                ['Dobras Cutâneas (Jackson/Pollock 7)', 'Circunferências (Naval)'], 
                key='calc_method_radio'
            )

        with col_medidas:
            # [Medidas de Circunferência/Dobras Inalteradas]
            st.markdown("##### Medidas Requeridas (cm ou mm)")
            waist = initial_values['waist']; hip = 0.0; neck = 0.0
            
            if calc_method == 'Circunferências (Naval)':
                st.info("Medidas em **cm**. Utilize fita métrica.")
                neck = st.number_input("Pescoço (cm)", min_value=25.0, format="%.1f", value=initial_values['neck'])
                waist = st.number_input("Cintura (cm)", min_value=50.0, format="%.1f", value=initial_values['waist'])
                if gender == 'Feminino':
                    hip = st.number_input("Quadril (cm)", min_value=70.0, format="%.1f", value=initial_values['hip'])
                
                if gender == 'Masculino' and waist <= neck:
                    st.error("Para o cálculo Naval (Homens), a Cintura deve ser maior que o Pescoço.")
                
            else: # Dobras Cutâneas (Jackson/Pollock 7)
                st.info("Medidas em **mm**. Utilize um adipômetro (dobras cutâneas).")
                st.markdown("---")
                sk_col1, sk_col2, sk_col3 = st.columns(3)
                sk_chest = sk_col1.number_input("Peitoral (mm)", min_value=1.0, format="%.1f", value=initial_values['sk_chest'])
                sk_triceps = sk_col1.number_input("Tríceps (mm)", min_value=1.0, format="%.1f", value=initial_values['sk_triceps'])
                sk_subscap = sk_col1.number_input("Subescapular (mm)", min_value=1.0, format="%.1f", value=initial_values['sk_subscap'])
                sk_midax = sk_col2.number_input("Axilar Média (mm)", min_value=1.0, format="%.1f", value=initial_values['sk_midax'])
                sk_supra = sk_col2.number_input("Suprailíaca (mm)", min_value=1.0, format="%.1f", value=initial_values['sk_supra'])
                sk_abdomen = sk_col3.number_input("Abdominal (mm)", min_value=1.0, format="%.1f", value=initial_values['sk_abdomen'])
                sk_thigh = sk_col3.number_input("Coxa (mm)", min_value=1.0, format="%.1f", value=initial_values['sk_thigh'])
                waist = st.number_input("Cintura (cm) - Opcional para Histórico", min_value=50.0, format="%.1f", value=initial_values['waist'])


        st.markdown("---")
        
        col_calc, col_save = st.columns(2)
        
        # --- Lógica de Cálculo (Inalterada) ---
        if 'calculated_bf' in st.session_state and st.session_state.get('last_method') == calc_method:
            pass
        else:
            st.session_state.pop('calculated_bf', None)
            st.session_state.pop('waist_circ_save', None)
            st.session_state.pop('bmi_save', None)
            
        with col_calc:
            if st.form_submit_button("Calcular Composição Corporal", type="secondary"):
                bmi_val = calculate_bmi(weight, height)
                
                if calc_method == 'Circunferências (Naval)':
                    calculated_bf = calculate_body_fat_navy(gender, height, neck, waist, hip)
                else:
                    calculated_bf = calculate_body_fat_jp7(gender, age, sk_chest, sk_triceps, sk_subscap, sk_midax, sk_supra, sk_abdomen, sk_thigh)
                
                st.session_state['calculated_bf'] = calculated_bf
                st.session_state['waist_circ_save'] = waist
                st.session_state['bmi_save'] = bmi_val
                st.session_state['last_method'] = calc_method
                st.rerun() 
                
        with col_save:
            if 'calculated_bf' in st.session_state:
                bf_val = st.session_state['calculated_bf']
                bmi_val = st.session_state['bmi_save']
                mg_val = weight * (bf_val / 100)
                mm_val = weight - mg_val
                
                st.markdown("##### Resultados Calculados:")
                st.metric("IMC", f"{bmi_val:.1f}")
                st.metric("% Gordura", f"{bf_val:.1f} %")
                st.metric("Massa Gorda", f"{mg_val:.1f} kg")
                st.metric("Massa Magra", f"{mm_val:.1f} kg")
                
                if gender == 'Feminino' and calc_method == 'Circunferências (Naval)' and hip > 0:
                     whr = waist / hip
                     whr_risk = "Baixo"
                     if whr > 0.85: whr_risk = "Moderado"
                     if whr > 0.90: whr_risk = "Alto"
                     st.metric("Risco Cintura-Quadril", f"{whr:.2f} ({whr_risk})")


                if st.form_submit_button("Salvar Métrica no Histórico", type="primary"):
                    date_str = date.strftime('%Y-%m-%d')
                    
                    # Salva a métrica associada ao user_id
                    if save_body_metric(user_id, date_str, weight, bf_val, st.session_state['waist_circ_save'], bmi_val):
                        st.success(f"Métrica de {date_str} registrada com sucesso para {st.session_state['username']}!")
                        del st.session_state['calculated_bf']
                        del st.session_state['waist_circ_save']
                        del st.session_state['bmi_save']
                        st.session_state.pop('last_method', None)
                        st.rerun()
                    else:
                        st.error("Erro ao salvar métrica.")
            else:
                st.warning("Pressione 'Calcular Composição Corporal' antes de salvar.")


    st.markdown("---")
    
    # --- 2. Histórico e Análise ---
    st.subheader("Histórico de Composição Corporal")
    # Busca métricas APENAS do usuário logado
    df_metrics = get_body_metrics(user_id)
    
    if df_metrics.empty:
        st.info(f"Nenhuma métrica registrada ainda para {st.session_state['username']}.")
        return

    # [Visualização e Gráficos Inalterados]
    last_metric = df_metrics.iloc[0]
    st.markdown(f"##### Última Avaliação ({last_metric['date'].strftime('%d/%m/%Y')}):")
    
    col_w, col_bf, col_mg, col_mm, col_bmi = st.columns(5)
    col_w.metric("Peso", f"{last_metric['weight']:.1f} kg")
    col_bf.metric("% Gordura", f"{last_metric['body_fat_perc']:.1f} %")
    col_mg.metric("Massa Gorda", f"{last_metric['Massa Gorda (kg)']:.1f} kg")
    col_mm.metric("Massa Magra", f"{last_metric['Massa Magra (kg)']:.1f} kg")
    col_bmi.metric("IMC", f"{last_metric['bmi']:.1f}")
    
    st.markdown("---")

    df_metrics = df_metrics.sort_values(by='date')
    st.line_chart(df_metrics, x='date', y=['weight', 'Massa Magra (kg)', 'Massa Gorda (kg)'])
    st.line_chart(df_metrics, x='date', y=['body_fat_perc', 'bmi'])


def page_relatorios():
    user_id = st.session_state['user_id']
    st.header(f"📊 Relatórios e Análise de Nutrientes - {st.session_state['username']}")
    st.info("Gráfico de análise da composição dos alimentos cadastrados.")
    
    st.subheader("Distribuição de Nutrientes Cadastrados")
    
    # Busca alimentos APENAS do usuário logado
    df_foods = get_all_foods(user_id) 
    
    if df_foods.empty:
        st.warning("Cadastre alimentos para visualizar a análise.")
        return

    # [Cálculo e Gráfico de Pizza Inalterados]
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
    # Garante que o ID do usuário está no estado da sessão
    if 'user_id' not in st.session_state:
        st.session_state['user_id'] = get_user_id(st.session_state['username'])
        if st.session_state['user_id'] is None:
             st.error("Erro fatal: Usuário logado não encontrado no banco de dados. Fazendo logout.")
             st.session_state['logged_in'] = False
             st.rerun()
             return

    st.sidebar.markdown(f"**Usuário Logado:** `{st.session_state.get('username', 'N/A')}`")
    st.sidebar.markdown("---")
    
    PAGES = {
        "Planejador Inteligente": page_planejador_inteligente,
        "Avaliação Física": page_avaliacao_fisica,
        "Banco de Alimentos (TACO)": page_receitas, 
        "Relatórios": page_relatorios
    }

    st.sidebar.title("EveFii v11 Multiusuário")
    selection = st.sidebar.radio("Navegação", list(PAGES.keys()))
    
    st.sidebar.markdown("---")
    if st.sidebar.button("Logout", type="secondary"):
        st.session_state['logged_in'] = False
        st.session_state.pop('username', None)
        st.session_state.pop('user_id', None)
        st.rerun()

    PAGES[selection]()

def show_login():
    st.title("EveFii v11 — Suporte Multiusuário")
    st.subheader("Faça Login ou Cadastre-se")
    
    tab_login, tab_register = st.tabs(["Login", "Cadastrar Novo Usuário"])
    
    with tab_login:
        with st.form("login_form"):
            username = st.text_input("Usuário")
            password = st.text_input("Senha", type='password')
            login_submitted = st.form_submit_button("Login", type="primary")
            
            if login_submitted:
                if verify_user(username, password):
                    st.session_state['logged_in'] = True
                    st.session_state['username'] = username
                    st.session_state['user_id'] = get_user_id(username) # Armazena o ID
                    st.rerun()
                else:
                    st.error("Usuário ou Senha inválidos. (Padrão: eve / change-me)")

    with tab_register:
        with st.form("register_form"):
            new_username = st.text_input("Novo Usuário (Ex: esposa)")
            new_password = st.text_input("Nova Senha", type='password')
            register_submitted = st.form_submit_button("Cadastrar", type="secondary")
            
            if register_submitted:
                if len(new_username) < 3 or len(new_password) < 5:
                    st.error("Usuário deve ter 3+ caracteres e Senha 5+.")
                elif register_user(new_username, new_password):
                    st.success(f"Usuário '{new_username}' cadastrado com sucesso! Faça login.")
                else:
                    st.error(f"Erro: Usuário '{new_username}' já existe.")


# --- Início da Execução ---

if __name__ == "__main__":
    
    st.set_page_config(page_title="EveFii v11 Nutrição", layout="wide")
    
    init_db()
    
    os.makedirs(PHOTOS_DIR, exist_ok=True)
    
    if 'logged_in' not in st.session_state:
        st.session_state['logged_in'] = False

    if st.session_state['logged_in']:
        main_app()
    else:
        show_login()
