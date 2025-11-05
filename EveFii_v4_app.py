# EveFii_v7_app.py - Versão FINAL (Gramas, Refeições, Edição/Exclusão + Avaliação Física)

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

# 2. Inicialização do Banco de Dados 
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
    
    # Tabela de Métricas Corporais
    cur.execute('''
        CREATE TABLE IF NOT EXISTS body_metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT, 
            date TEXT, 
            weight REAL, 
            body_fat_perc REAL,
            waist_circ REAL
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

# 4. Funções de Alimentos (CRUDS - Inalteradas)
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

# 5. Funções de Métricas Corporais (NOVA SEÇÃO)
def save_body_metric(date, weight, body_fat_perc, waist_circ):
    conn = get_conn(); cur = conn.cursor()
    try:
        cur.execute("INSERT INTO body_metrics (date, weight, body_fat_perc, waist_circ) VALUES (?, ?, ?, ?)", 
                    (date, weight, body_fat_perc, waist_circ))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def get_body_metrics():
    conn = get_conn(); 
    metrics = pd.read_sql("SELECT date, weight, body_fat_perc, waist_circ FROM body_metrics ORDER BY date DESC", conn)
    conn.close()
    
    if metrics.empty:
        return metrics
        
    # Cálculo da Massa Gorda (MG) e Massa Magra (MM)
    metrics['date'] = pd.to_datetime(metrics['date'])
    metrics['Massa Gorda (kg)'] = metrics['weight'] * (metrics['body_fat_perc'] / 100)
    metrics['Massa Magra (kg)'] = metrics['weight'] - metrics['Massa Gorda (kg)']
    
    return metrics

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

def run_optimization(targets, meal_foods, meal_names):
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

    for i, selected_foods in enumerate(meal_foods):
        meal_name = meal_names[i] # Nome da refeição
        
        if not selected_foods:
            final_plan.append({'Refeição': meal_name, 'Alimento': 'Nenhum', 'Gramas': 0})
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
                        'Refeição': meal_name,
                        'Alimento': food_name,
                        'Gramas': round(v.varValue, 1),
                    })
        else:
            optimization_failed = True
            st.error(f"❌ Otimização Falhou para **{meal_name}**. Não foi possível atingir as metas com os alimentos selecionados.")
            return

    # --- 3. Resultado Final ---
    if not optimization_failed:
        st.subheader("3. Dieta Final Otimizada (Gramas por Refeição)")
        st.success("✅ Plano detalhado gerado com sucesso!")
        
        df_final = pd.DataFrame(final_plan)
        
        # Calcula macros totais para exibição
        # Note: Acessamos o DF completo do targets, limpando o nome da variável de decisão.
        df_foods_lookup = targets['df_foods'].set_index('name')
        
        total_prot = df_final.apply(lambda row: df_foods_lookup.loc[row['Alimento'].replace(' ', '_'), 'protein'] * (row['Gramas'] / 100) if row['Alimento'] != 'Nenhum' and row['Alimento'].replace(' ', '_') in df_foods_lookup.index else 0, axis=1).sum()
        total_carbs = df_final.apply(lambda row: df_foods_lookup.loc[row['Alimento'].replace(' ', '_'), 'carbs'] * (row['Gramas'] / 100) if row['Alimento'] != 'Nenhum' and row['Alimento'].replace(' ', '_') in df_foods_lookup.index else 0, axis=1).sum()
        total_fat = df_final.apply(lambda row: df_foods_lookup.loc[row['Alimento'].replace(' ', '_'), 'fat'] * (row['Gramas'] / 100) if row['Alimento'] != 'Nenhum' and row['Alimento'].replace(' ', '_') in df_foods_lookup.index else 0, axis=1).sum()


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
        
        # Inicializa o estado dos nomes das refeições e dos alimentos selecionados
        if 'meal_foods' not in st.session_state or len(st.session_state['meal_foods']) != targets['num_meals']:
            st.session_state['meal_foods'] = [[] for _ in range(targets['num_meals'])]
        if 'meal_names' not in st.session_state or len(st.session_state['meal_names']) != targets['num_meals']:
            st.session_state['meal_names'] = [f"Refeição {i+1}" for i in range(targets['num_meals'])]


        all_food_names = targets['df_foods']['name'].tolist()
        
        # Interface de personalização do nome e seleção
        st.markdown("##### Personalize os Nomes e Selecione os Alimentos:")
        
        meal_cols = st.columns(targets['num_meals'])
        
        for i in range(targets['num_meals']):
            with meal_cols[i]:
                # Campo para alterar o nome da refeição
                st.session_state['meal_names'][i] = st.text_input(
                    f"Nome da Refeição {i+1}", 
                    value=st.session_state['meal_names'][i], 
                    key=f'meal_name_{i}'
                )
                
                # Seleção dos Alimentos
                st.session_state['meal_foods'][i] = st.multiselect(
                    f"Alimentos para {st.session_state['meal_names'][i]}",
                    options=all_food_names,
                    default=st.session_state['meal_foods'][i],
                    key=f'multiselect_{i}'
                )
        
        st.markdown("---")
        if st.button("Gerar Dieta Final em Gramas", type="primary"):
            run_optimization(targets, st.session_state['meal_foods'], st.session_state['meal_names'])


def page_receitas():
    st.header("🍚 Banco de Alimentos (TACO) - 100g")
    st.info("Cadastre/Edite os dados nutricionais de cada alimento para uma porção de **100g**.")

    df_foods = get_all_foods()
    
    # --- 1. Visualização e Seleção para Edição ---
    st.subheader("Alimentos Cadastrados (por 100g)")
    if not df_foods.empty:
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
                    # Usando st.session_state para confirmar exclusão
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
                st.rerun()
            else:
                st.error(f"Erro: O alimento '{nome}' já existe. Por favor, use um nome diferente.")

def page_avaliacao_fisica():
    st.header("🏋️ Avaliação Física e Progresso Corporal")
    st.info("Monitore seu peso, percentual de gordura e as mudanças na composição corporal.")
    
    # --- 1. Formulário de Cadastro de Métrica ---
    st.subheader("Registrar Nova Métrica")
    with st.form("new_metric"):
        date = st.date_input("Data da Avaliação", value=datetime.today())
        col1, col2, col3 = st.columns(3)
        with col1:
            weight = st.number_input("Peso (kg)", min_value=30.0, format="%.1f", value=75.0)
        with col2:
            # Porcentagem de Gordura (ex: obtido por bioimpedância ou dobras cutâneas)
            body_fat_perc = st.number_input("% de Gordura Corporal", min_value=5.0, max_value=50.0, format="%.1f", value=20.0)
        with col3:
            waist_circ = st.number_input("Circunferência Cintura (cm)", min_value=50.0, format="%.1f", value=80.0)

        submitted = st.form_submit_button("Salvar Métrica", type="primary")
        if submitted:
            date_str = date.strftime('%Y-%m-%d')
            if save_body_metric(date_str, weight, body_fat_perc, waist_circ):
                st.success(f"Métrica de {date_str} registrada com sucesso!")
                st.rerun()
            else:
                st.error("Erro ao salvar métrica.")
    
    st.markdown("---")
    
    # --- 2. Histórico e Análise ---
    st.subheader("Histórico de Composição Corporal")
    df_metrics = get_body_metrics()
    
    if df_metrics.empty:
        st.info("Nenhuma métrica registrada ainda. Adicione uma acima!")
        return

    # Exibe a última avaliação
    last_metric = df_metrics.iloc[0]
    st.markdown(f"##### Última Avaliação ({last_metric['date'].strftime('%d/%m/%Y')}):")
    
    col_w, col_bf, col_mg, col_mm = st.columns(4)
    col_w.metric("Peso", f"{last_metric['weight']:.1f} kg")
    col_bf.metric("% Gordura", f"{last_metric['body_fat_perc']:.1f} %")
    col_mg.metric("Massa Gorda", f"{last_metric['Massa Gorda (kg)']:.1f} kg")
    col_mm.metric("Massa Magra", f"{last_metric['Massa Magra (kg)']:.1f} kg")
    
    st.markdown("---")

    # Gráficos de Progresso
    df_metrics = df_metrics.sort_values(by='date')
    st.line_chart(df_metrics, x='date', y=['weight', 'Massa Magra (kg)', 'Massa Gorda (kg)'])
    st.line_chart(df_metrics, x='date', y='body_fat_perc')


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
    st.sidebar.markdown(f"**Usuário Logado:** `{st.session_state.get('username', 'N/A')}`")
    st.sidebar.markdown("---")
    
    PAGES = {
        "Planejador Inteligente": page_planejador_inteligente,
        "Avaliação Física": page_avaliacao_fisica, # Nova página
        "Banco de Alimentos (TACO)": page_receitas, 
        "Relatórios": page_relatorios
    }

    st.sidebar.title("EveFii v7 Completo (Nutrição)")
    selection = st.sidebar.radio("Navegação", list(PAGES.keys()))
    
    st.sidebar.markdown("---")
    if st.sidebar.button("Logout", type="secondary"):
        st.session_state['logged_in'] = False
        st.session_state.pop('username', None)
        st.rerun()

    PAGES[selection]()

def show_login():
    st.title("EveFii v7 — Focado em Nutrição")
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
    
    st.set_page_config(page_title="EveFii v7 Nutrição", layout="wide")
    
    init_db()
    
    os.makedirs(PHOTOS_DIR, exist_ok=True)
    
    if 'logged_in' not in st.session_state:
        st.session_state['logged_in'] = False

    if st.session_state['logged_in']:
        main_app()
    else:
        show_login()
