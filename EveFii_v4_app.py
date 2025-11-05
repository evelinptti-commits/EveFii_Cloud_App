# EveFii_v17_app.py - Versão Completa com Fibra, Sódio (Restrição) e Calculadora de Água (Hidratação)

# Imports
import streamlit as st
import sqlite3
import hashlib
import os
import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime
# from pulp import LpProblem, LpMinimize, LpVariable, PULP_CBC_CMD, LpStatus, value, lpSum, const # <--- Desativado
import math
from fpdf import FPDF 
import io
import shutil 

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

# Funções de Usuário e Perfil 
def get_user_id(username):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT id FROM users WHERE username = ?", (username,))
    user = cur.fetchone()
    conn.close()
    return user['id'] if user else None

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

def save_user_profile(user_id, gender, height, age):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("INSERT OR REPLACE INTO user_profile (user_id, gender, height, age) VALUES (?, ?, ?, ?)", 
                (user_id, gender, height, age))
    conn.commit()
    conn.close()

def get_user_profile(user_id):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT gender, height, age FROM user_profile WHERE user_id = ?", (user_id,))
    profile = cur.fetchone()
    conn.close()
    return dict(profile) if profile else None

# 2. Inicialização do Banco de Dados (Com Correção de Migração para v17: SÓDIO, FIBRA e SINTAXE)
@st.cache_resource
def init_db():
    conn = get_conn(); cur = conn.cursor()
    
    # Tabela de Usuários
    cur.execute('CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE, password_hash TEXT)')
    
    # Tabela de Perfil de Usuário
    cur.execute('''
        CREATE TABLE IF NOT EXISTS user_profile (
            user_id INTEGER PRIMARY KEY,
            gender TEXT,
            height REAL,
            age INTEGER,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    
    # Tabela de Alimentos (Adicionando FIBRA e SÓDIO) - CORREÇÃO DE SINTAXE AQUI
    cur.execute('''
        CREATE TABLE IF NOT EXISTS recipes (
            id INTEGER PRIMARY KEY AUTOINCREMENT, 
            user_id INTEGER, 
            name TEXT, 
            cost REAL, 
            calories INTEGER, 
            protein REAL, 
            carbs REAL, 
            fat REAL,
            fiber REAL,
            sodium REAL 
        )
    ''')
    
    # Tabela de Métricas
    cur.execute('''
        CREATE TABLE IF NOT EXISTS body_metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT, 
            user_id INTEGER, 
            date TEXT, 
            weight REAL, 
            body_fat_perc REAL,
            waist_circ REAL,
            bmi REAL,
            photo_path TEXT  
        )
    ''')
    
    # --- CORREÇÕES DE MIGRAÇÃO (Garantindo todas as colunas) ---
    try: cur.execute("SELECT bmi FROM body_metrics LIMIT 1")
    except sqlite3.OperationalError: cur.execute("ALTER TABLE body_metrics ADD COLUMN bmi REAL")
    try: cur.execute("SELECT user_id FROM body_metrics LIMIT 1")
    except sqlite3.OperationalError: cur.execute("ALTER TABLE body_metrics ADD COLUMN user_id INTEGER")
    try: cur.execute("SELECT user_id FROM recipes LIMIT 1")
    except sqlite3.OperationalError: cur.execute("ALTER TABLE recipes ADD COLUMN user_id INTEGER")
    try: cur.execute("SELECT photo_path FROM body_metrics LIMIT 1")
    except sqlite3.OperationalError: cur.execute("ALTER TABLE body_metrics ADD COLUMN photo_path TEXT")
    try: cur.execute("SELECT fiber FROM recipes LIMIT 1")
    except sqlite3.OperationalError: 
        cur.execute("ALTER TABLE recipes ADD COLUMN fiber REAL DEFAULT 0.0")
    # Migração de v16: Adicionar sodium
    try: cur.execute("SELECT sodium FROM recipes LIMIT 1")
    except sqlite3.OperationalError: 
        cur.execute("ALTER TABLE recipes ADD COLUMN sodium REAL DEFAULT 0.0") 

    # Adiciona usuário padrão se o banco estiver vazio
    cur.execute("SELECT COUNT(*) FROM users"); c = cur.fetchone()[0]
    if c == 0:
        pw = hashlib.sha256('change-me'.encode()).hexdigest()
        cur.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)", ('eve', pw))
    
    conn.commit()
    conn.close()
    
    # Garante que a pasta de fotos exista
    os.makedirs(PHOTOS_DIR, exist_ok=True)

# 3. Funções de Alimentos (CRUDS e Importação CSV)
def save_food(user_id, name, cal, prot, carb, fat, fiber, sodium): 
    conn = get_conn(); cur = conn.cursor()
    try:
        cur.execute("INSERT INTO recipes (user_id, name, cost, calories, protein, carbs, fat, fiber, sodium) VALUES (?, ?, 0.0, ?, ?, ?, ?, ?, ?)", 
                    (user_id, name, cal, prot, carb, fat, fiber, sodium)) 
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def get_all_foods(user_id):
    conn = get_conn(); 
    foods = pd.read_sql("SELECT id, name, cost, calories, protein, carbs, fat, fiber, sodium FROM recipes WHERE user_id = ?", conn, params=(user_id,))
    conn.close()
    return foods

def get_food_by_id(food_id):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT id, name, calories, protein, carbs, fat, fiber, sodium FROM recipes WHERE id=?", (food_id,))
    food = cur.fetchone()
    conn.close()
    return dict(food) if food else None

def update_food(food_id, name, cal, prot, carb, fat, fiber, sodium): 
    conn = get_conn(); cur = conn.cursor()
    try:
        cur.execute("UPDATE recipes SET name=?, calories=?, protein=?, carbs=?, fat=?, fiber=?, sodium=? WHERE id=?", 
                    (name, cal, prot, carb, fat, fiber, sodium, food_id)) 
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

def import_foods_from_csv(user_id, csv_file):
    """Importa alimentos do CSV para o banco de dados do usuário."""
    try:
        df = pd.read_csv(csv_file)
        required_cols = ['name', 'calories', 'protein', 'carbs', 'fat']
        
        if not all(col in df.columns for col in required_cols):
            return 0, f"O arquivo CSV deve conter as colunas: {', '.join(required_cols)}"
        
        df['fiber'] = df.get('fiber', 0.0)
        df['sodium'] = df.get('sodium', 0.0) 
        df = df[required_cols + ['fiber', 'sodium']]
        
        df['cost'] = 0.0 
        df['user_id'] = user_id
        
        df = df.astype({
            'name': str, 'calories': int, 'protein': float, 'carbs': float, 'fat': float,
            'fiber': float, 'sodium': float, 'user_id': int, 'cost': float
        })
        
        conn = get_conn()
        count_before = pd.read_sql("SELECT COUNT(*) FROM recipes WHERE user_id = ?", conn, params=(user_id,)).iloc[0, 0]
        
        df[['user_id', 'name', 'cost', 'calories', 'protein', 'carbs', 'fat', 'fiber', 'sodium']].to_sql(
            'recipes', conn, if_exists='append', index=False
        )
        
        count_after = pd.read_sql("SELECT COUNT(*) FROM recipes WHERE user_id = ?", conn, params=(user_id,)).iloc[0, 0]
        conn.close()
        
        return count_after - count_before, None
        
    except Exception as e:
        return 0, f"Erro ao processar o CSV: {e}"


# 4. Funções de Planejador e Otimização 
def calculate_smart_macros(gender, weight, height, age, activity_level_factor, goal):
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
    
    target_sodium = 2300 
    
    return int(final_cal), target_prot, target_carbs, target_fat, target_sodium

# --- NOVA FUNÇÃO: Cálculo de Macros de um Plano Manual ---
def calculate_macros_from_plan(df_plan, df_foods):
    """Calcula os macros totais (Cal, Prot, Carb, Fat, Fiber, Sodium) a partir de um DataFrame de plano de refeição (Alimento, Gramas)."""
    if df_plan.empty:
        return {'cal': 0, 'prot': 0.0, 'carbs': 0.0, 'fat': 0.0, 'fiber': 0.0, 'sodium': 0.0}

    # Remove linhas com alimento vazio ou gramas nulas/zero
    df_plan = df_plan[df_plan['Alimento'].notna() & (df_plan['Gramas'].fillna(0) > 0)]
    
    if df_plan.empty:
        return {'cal': 0, 'prot': 0.0, 'carbs': 0.0, 'fat': 0.0, 'fiber': 0.0, 'sodium': 0.0}

    # Junta o plano com os dados nutricionais
    df_merged = pd.merge(
        df_plan, 
        df_foods.set_index('name')[['calories', 'protein', 'carbs', 'fat', 'fiber', 'sodium']], 
        left_on='Alimento', 
        right_index=True, 
        how='left'
    )
    
    # Previne NaN em caso de alimentos recém-adicionados e não salvos no DB
    df_merged = df_merged.fillna(0)

    # Calcula os macros
    grams_ratio = df_merged['Gramas'] / 100.0
    
    total_cal = (df_merged['calories'] * grams_ratio).sum()
    total_prot = (df_merged['protein'] * grams_ratio).sum()
    total_carbs = (df_merged['carbs'] * grams_ratio).sum()
    total_fat = (df_merged['fat'] * grams_ratio).sum()
    total_fiber = (df_merged['fiber'] * grams_ratio).sum()
    total_sodium = (df_merged['sodium'] * grams_ratio).sum()

    return {
        'cal': int(total_cal), 
        'prot': round(total_prot, 1), 
        'carbs': round(total_carbs, 1), 
        'fat': round(total_fat, 1),
        'fiber': round(total_fiber, 1),
        'sodium': round(total_sodium, 0)
    }

# def run_optimization(targets, meal_foods, meal_names): # <--- Otimização Desativada (Comentada)
#     num_meals = targets['num_meals']
#     meal_targets = {
# # ... (código da função de otimização) ...
#     return


# --- Funções de Métricas Corporais ---
def calculate_body_fat_navy(gender, height, neck, waist, hip=0):
# ... (código da função) ...
    h_in = height * 0.3937; n_in = neck * 0.3937; w_in = waist * 0.3937; hip_in = hip * 0.3937
    if gender == 'Masculino':
        try: bf = 495 / (1.0324 - 0.19077 * math.log10(w_in - n_in) + 0.15456 * math.log10(h_in)) - 450
        except ValueError: bf = 5.0
    else:
        try: bf = 495 / (1.29579 - 0.35004 * math.log10(w_in + hip_in - n_in) + 0.22100 * math.log10(h_in)) - 450
        except ValueError: bf = 10.0 
    return max(5.0, min(50.0, bf))

def calculate_body_fat_jp7(gender, age, sk_chest, sk_triceps, sk_subscap, sk_midax, sk_supra, sk_abdomen, sk_thigh):
# ... (código da função) ...
    S7SKF = sk_chest + sk_triceps + sk_subscap + sk_midax + sk_supra + sk_abdomen + sk_thigh
    if S7SKF <= 0: return 5.0 
    try:
        if gender == 'Masculino':
            DB = 1.112 - (0.00043499 * S7SKF) + (0.00000055 * S7SKF**2) - (0.00028826 * age)
        else: 
            DB = 1.0970 - (0.00046971 * S7SKF) + (0.00000056 * S7SKF**2) - (0.00012828 * age)
        bf = (495 / DB) - 450
    except Exception: bf = 5.0 
    return max(5.0, min(50.0, bf))

def calculate_bmi(weight, height):
    height_m = height / 100.0
    if height_m <= 0: return 0.0
    return weight / (height_m ** 2)

def save_uploaded_photo(uploaded_file, user_id):
    if uploaded_file:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_extension = os.path.splitext(uploaded_file.name)[1]
        unique_filename = f"{user_id}_{timestamp}{file_extension}"
        file_path = os.path.join(PHOTOS_DIR, unique_filename)
        with open(file_path, "wb") as f: f.write(uploaded_file.getbuffer())
        return unique_filename 
    return None

def save_body_metric(user_id, date, weight, body_fat_perc, waist_circ, bmi, photo_path): 
# ... (código da função) ...
    conn = get_conn(); cur = conn.cursor()
    try:
        cur.execute("INSERT INTO body_metrics (user_id, date, weight, body_fat_perc, waist_circ, bmi, photo_path) VALUES (?, ?, ?, ?, ?, ?, ?)", 
                    (user_id, date, weight, body_fat_perc, waist_circ, bmi, photo_path))
        conn.commit()
        return True
    except sqlite3.IntegrityError: return False
    finally: conn.close()

def get_body_metrics(user_id):
# ... (código da função) ...
    conn = get_conn(); 
    metrics = pd.read_sql("SELECT date, weight, body_fat_perc, waist_circ, bmi, photo_path FROM body_metrics WHERE user_id = ? ORDER BY date DESC", conn, params=(user_id,))
    conn.close()
    if metrics.empty: return metrics
    metrics['date'] = pd.to_datetime(metrics['date'])
    metrics['Massa Gorda (kg)'] = metrics['weight'] * (metrics['body_fat_perc'] / 100)
    metrics['Massa Magra (kg)'] = metrics['weight'] - metrics['Massa Gorda (kg)']
    return metrics

# --- Geração de PDF ---
class PDF(FPDF):
    def header(self):
# ... (código da função) ...
        self.set_font('Arial', 'B', 15)
        self.cell(0, 10, 'EveFii - Relatório de Nutrição', 0, 1, 'C')
        self.ln(5)

    def footer(self):
# ... (código da função) ...
        self.set_y(-15)
        self.set_font('Arial', 'I', 8)
        self.cell(0, 10, f'Página {self.page_no()}', 0, 0, 'C')
        
    def cell_utf8(self, w, h, txt, border=0, ln=0, align=''):
        self.cell(w, h, txt.encode('latin-1', 'replace').decode('latin-1'), border, ln, align)

def generate_diet_pdf(username, targets, df_plan, final_totals):
# ... (código da função) ...
    pdf = PDF('P', 'mm', 'A4')
    pdf.add_page()
    
    pdf.set_font('Arial', 'B', 16)
    pdf.cell_utf8(0, 10, f'Plano de Dieta Manual para {username}', 0, 1)
    pdf.ln(2)

    pdf.set_fill_color(220, 220, 220)
    pdf.set_font('Arial', 'B', 9)
    pdf.cell_utf8(25, 7, 'Calorias', 1, 0, 'C', 1)
    pdf.cell_utf8(25, 7, 'Proteína', 1, 0, 'C', 1)
    pdf.cell_utf8(25, 7, 'Carboidratos', 1, 0, 'C', 1)
    pdf.cell_utf8(25, 7, 'Gordura', 1, 0, 'C', 1)
    pdf.cell_utf8(25, 7, 'Fibra', 1, 0, 'C', 1)
    pdf.cell_utf8(25, 7, 'Sódio', 1, 1, 'C', 1) 

    pdf.set_font('Arial', '', 9)
    pdf.cell_utf8(25, 7, f'{final_totals["cal"]} kcal', 1, 0, 'C')
    pdf.cell_utf8(25, 7, f'{final_totals["prot"]:.1f} g', 1, 0, 'C')
    pdf.cell_utf8(25, 7, f'{final_totals["carbs"]:.1f} g', 1, 0, 'C')
    pdf.cell_utf8(25, 7, f'{final_totals["fat"]:.1f} g', 1, 0, 'C')
    pdf.cell_utf8(25, 7, f'{final_totals["fiber"]:.1f} g', 1, 0, 'C')
    pdf.cell_utf8(25, 7, f'{final_totals["sodium"]:.0f} mg', 1, 1, 'C') 
    
    pdf.ln(5)
    
    pdf.set_font('Arial', 'B', 12)
    pdf.cell_utf8(0, 10, 'Detalhes da Dieta:', 0, 1)
    
    pdf.set_fill_color(220, 220, 220)
    pdf.set_font('Arial', 'B', 10)
    pdf.cell_utf8(50, 7, 'Refeição', 1, 0, 'C', 1)
    pdf.cell_utf8(90, 7, 'Alimento', 1, 0, 'C', 1)
    pdf.cell_utf8(30, 7, 'Quantidade', 1, 1, 'C', 1)
    
    pdf.set_font('Arial', '', 10)
    for index, row in df_plan.iterrows():
        pdf.cell_utf8(50, 6, str(row['Refeição']), 1, 0, 'L')
        pdf.cell_utf8(90, 6, str(row['Alimento']), 1, 0, 'L')
        pdf.cell_utf8(30, 6, f"{row['Gramas']} g", 1, 1, 'R')
        
    return pdf.output(dest='S').encode('latin-1')

def generate_metrics_pdf(username, df_metrics):
# ... (código da função) ...
    pdf = PDF('P', 'mm', 'A4')
    pdf.add_page()
    
    pdf.set_font('Arial', 'B', 16)
    pdf.cell_utf8(0, 10, f'Relatório de Evolução Corporal de {username}', 0, 1)
    pdf.ln(5)

    pdf.set_fill_color(220, 220, 220)
    pdf.set_font('Arial', 'B', 10)
    pdf.cell_utf8(20, 7, 'Data', 1, 0, 'C', 1)
    pdf.cell_utf8(25, 7, 'Peso (kg)', 1, 0, 'C', 1)
    pdf.cell_utf8(20, 7, '% Gord.', 1, 0, 'C', 1)
    pdf.cell_utf8(30, 7, 'Massa Gorda', 1, 0, 'C', 1)
    pdf.cell_utf8(30, 7, 'Massa Magra', 1, 0, 'C', 1)
    pdf.cell_utf8(20, 7, 'Cintura', 1, 0, 'C', 1)
    pdf.cell_utf8(15, 7, 'IMC', 1, 1, 'C', 1)

    pdf.set_font('Arial', '', 8)
    df_metrics_chrono = df_metrics.sort_values(by='date')
    
    for index, row in df_metrics_chrono.iterrows():
        pdf.cell_utf8(20, 6, row['date'].strftime('%d/%m/%Y'), 1, 0, 'C')
        pdf.cell_utf8(25, 6, f"{row['weight']:.1f}", 1, 0, 'R')
        pdf.cell_utf8(20, 6, f"{row['body_fat_perc']:.1f}", 1, 0, 'R')
        pdf.cell_utf8(30, 6, f"{row['Massa Gorda (kg)']:.1f} kg", 1, 0, 'R')
        pdf.cell_utf8(30, 6, f"{row['Massa Magra (kg)']:.1f} kg", 1, 0, 'R')
        pdf.cell_utf8(20, 6, f"{row['waist_circ']:.1f} cm", 1, 0, 'R')
        pdf.cell_utf8(15, 6, f"{row['bmi']:.1f}", 1, 1, 'R')
        
    if len(df_metrics_chrono) > 1:
        first = df_metrics_chrono.iloc[0]
        last = df_metrics_chrono.iloc[-1]
        
        pdf.ln(5)
        pdf.set_font('Arial', 'B', 12)
        pdf.cell_utf8(0, 10, 'Resumo da Evolução (Total):', 0, 1)
        
        def format_diff_pdf(start, end, metric_name, unit):
            diff = end - start
            diff_str = f"{'+' if diff > 0 else ''}{diff:.1f} {unit}"
            if metric_name in ['Peso', '% Gordura', 'Massa Gorda']:
                color = (0, 100, 0) if diff < 0 else (180, 0, 0)
            else: 
                color = (0, 100, 0) if diff > 0 else (180, 0, 0) 

            pdf.set_text_color(*color)
            pdf.cell_utf8(0, 7, f"De {start:.1f} para {end:.1f} {unit} ({diff_str})", 0, 1)
            pdf.set_text_color(0, 0, 0) 
        
        pdf.set_font('Arial', 'B', 10)
        pdf.cell_utf8(50, 7, 'Peso Corporal:', 0, 0)
        pdf.set_font('Arial', '', 10)
        format_diff_pdf(first['weight'], last['weight'], 'Peso', 'kg')
        
        pdf.set_font('Arial', 'B', 10)
        pdf.cell_utf8(50, 7, '% Gordura:', 0, 0)
        pdf.set_font('Arial', '', 10)
        format_diff_pdf(first['body_fat_perc'], last['body_fat_perc'], '% Gordura', '%')
        
        pdf.set_font('Arial', 'B', 10)
        pdf.cell_utf8(50, 7, 'Massa Gorda:', 0, 0)
        pdf.set_font('Arial', '', 10)
        format_diff_pdf(first['Massa Gorda (kg)'], last['Massa Gorda (kg)'], 'Massa Gorda', 'kg')

        pdf.set_font('Arial', 'B', 10)
        pdf.cell_utf8(50, 7, 'Massa Magra:', 0, 0)
        pdf.set_font('Arial', '', 10)
        format_diff_pdf(first['Massa Magra (kg)'], last['Massa Magra (kg)'], 'Massa Magra', 'kg')

        
    return pdf.output(dest='S').encode('latin-1')

# --- Funções Específicas da V17 (Hidratação) ---

def calculate_water_goal(weight_kg, age_years):
# ... (código da função) ...
    """Calcula a meta de ingestão de água em litros com base no peso e idade."""
    if age_years < 18:
        ml_per_kg = 40
    elif age_years <= 55:
        ml_per_kg = 35
    elif age_years <= 65:
        ml_per_kg = 30
    else:
        ml_per_kg = 25
        
    goal_ml = weight_kg * ml_per_kg
    goal_liters = goal_ml / 1000
    
    return goal_liters, ml_per_kg

# --- Estrutura das Páginas ---

def page_planejador_inteligente():
    user_id = st.session_state['user_id']
    st.header("✍️ Planejador Manual Reativo (Refeições e Gramas)")
    st.info("Digite as gramas dos alimentos e o sistema mostrará imediatamente seus totais e se você está atingindo as metas.")
    
    df_foods = get_all_foods(user_id) 
    
    if df_foods.empty:
        st.warning(f"🚨 Por favor, **{st.session_state['username']}**, cadastre alimentos na página 'Banco de Alimentos (TACO)' antes de planejar.")
        return

    profile = get_user_profile(user_id)
    df_metrics = get_body_metrics(user_id)
    
    initial_weight = df_metrics.iloc[0]['weight'] if not df_metrics.empty else 75.0
    initial_gender = profile.get('gender') if profile else 'Masculino'
    initial_height = int(profile.get('height')) if profile and profile.get('height') else 175
    initial_age = int(profile.get('age')) if profile and profile.get('age') else 30
    
    gender_options = ['Masculino', 'Feminino']
    gender_index = gender_options.index(initial_gender) if initial_gender in gender_options else 0
    
    st.subheader("1. Seus Dados e Objetivo (Metas Diárias)")
    with st.form("metas_calc_form"):
        col1, col2, col3 = st.columns(3)
        with col1:
            gender = st.selectbox("Gênero", gender_options, index=gender_index, key='plan_gender')
            weight = st.number_input(
                "Peso (kg) - Última Métrica", 
                min_value=30.0, 
                value=initial_weight, 
                format="%.1f",
                key='plan_weight',
                help="Preenchido automaticamente com sua última avaliação física."
            )
            goal = st.selectbox("Objetivo", ['Manutenção', 'Déficit Calórico', 'Hipertrofia Muscular'], key='plan_goal')
        with col2:
            height = st.number_input("Altura (cm)", min_value=100, value=initial_height, key='plan_height')
            age = st.number_input("Idade (anos)", min_value=15, value=initial_age, key='plan_age')
        with col3:
            activity_level = st.selectbox("Nível de Atividade", list(TDEE_FACTORS.keys()), key='plan_activity')
            num_meals = st.number_input("Número de Refeições/Dia", min_value=2, max_value=6, value=4, key='plan_num_meals')
            
        submitted_calc = st.form_submit_button("Calcular Metas Diárias", type="primary")

    if submitted_calc or 'targets' in st.session_state:
        if submitted_calc:
            save_user_profile(user_id, gender, height, age)
            activity_factor = TDEE_FACTORS[activity_level]
            target_cal, target_prot, target_carbs, target_fat, target_sodium = calculate_smart_macros(
                gender, weight, height, age, activity_factor, goal
            )
            st.session_state['targets'] = {
                'cal': target_cal, 'prot': target_prot, 'carbs': target_carbs, 'fat': target_fat,
                'sodium': target_sodium, 
                'num_meals': num_meals, 'df_foods': df_foods
            }
            # Inicializa a estrutura de dados do plano manual
            st.session_state['meal_names'] = [f"Refeição {i+1}" for i in range(num_meals)]
            # Inicializa o plano como um dicionário de DataFrames
            if 'manual_plan' not in st.session_state or len(st.session_state['manual_plan']) != num_meals:
                st.session_state['manual_plan'] = {
                    f"Refeição {i+1}": pd.DataFrame({'Alimento': [''], 'Gramas': [0]}).astype({'Alimento': 'str', 'Gramas': 'int32'}) 
                    for i in range(num_meals)
                }

        targets = st.session_state['targets']
        st.subheader("Metas Diárias Calculadas:")
        col_c, col_p, col_ca, col_g, col_s = st.columns(5)
        col_c.metric("Calorias Alvo", f"{targets['cal']} kcal")
        col_p.metric("Proteína Alvo", f"{targets['prot']} g")
        col_ca.metric("Carboidratos Alvo", f"{targets['carbs']} g")
        col_g.metric("Gordura Alvo", f"{targets['fat']} g")
        col_s.metric("Sódio Máximo", f"{targets['sodium']} mg") 
        st.markdown("---")
        
        # --- SEÇÃO 2: Construtor Manual de Refeições ---
        st.subheader(f"2. Construção Manual das Refeições ({targets['num_meals']} Refeições)")
        
        all_food_names = targets['df_foods']['name'].tolist()
        daily_plan_df_list = []
        
        meal_cols = st.columns(targets['num_meals'])
        
        for i in range(targets['num_meals']):
            meal_name = st.session_state['meal_names'][i]
            
            with meal_cols[i]:
                # Permite nomear a refeição
                meal_name_input = st.text_input(f"Nome Refeição {i+1}", value=meal_name, key=f'meal_name_input_{i}')
                st.session_state['meal_names'][i] = meal_name_input

                # Data Editor para o plano da refeição
                df_meal_current = st.session_state['manual_plan'][meal_name]
                
                # Streamlit Data Editor
                editor_config = {
                    'Alimento': st.column_config.SelectboxColumn(
                        "Alimento",
                        required=True,
                        options=all_food_names
                    ),
                    'Gramas': st.column_config.NumberColumn(
                        "Gramas (g)",
                        required=True,
                        min_value=1,
                        default=100,
                        step=1,
                        format="%d"
                    )
                }
                
                st.markdown(f"##### 🥣 {meal_name_input} (Meta por refeição: {int(targets['cal'] / targets['num_meals'])} kcal)")
                
                # Exibe o editor e armazena o resultado no Session State
                df_edited = st.data_editor(
                    df_meal_current,
                    column_config=editor_config,
                    num_rows="dynamic",
                    hide_index=True,
                    use_container_width=True,
                    key=f'editor_{i}'
                )
                
                # Atualiza o Session State com o DataFrame editado
                st.session_state['manual_plan'][meal_name] = df_edited
                
                # Recalcula e exibe os macros da refeição atual
                meal_macros = calculate_macros_from_plan(df_edited, targets['df_foods'])
                
                # Exibe o total da refeição em uma caixa
                st.markdown(f"""
                <div style='border: 1px solid #ddd; padding: 10px; border-radius: 5px; margin-top: 10px;'>
                    <h6 style='margin-top:0;'>Total {meal_name_input}</h6>
                    <small>Cal: {meal_macros['cal']} kcal | Prot: {meal_macros['prot']} g | Carb: {meal_macros['carbs']} g</small>
                </div>
                """, unsafe_allow_html=True)
                
                # Adiciona o plano da refeição (com nome da refeição) à lista para cálculo total
                df_edited['Refeição'] = meal_name_input
                daily_plan_df_list.append(df_edited.copy())

        st.markdown("---")
        
        # --- SEÇÃO 3: Totais Diários e Feedback ---
        st.subheader("3. Totais Diários e Feedback de Metas")
        
        # Combina todos os DataFrames de refeição em um único DataFrame diário
        if daily_plan_df_list:
            df_daily_plan = pd.concat(daily_plan_df_list, ignore_index=True)
            daily_totals = calculate_macros_from_plan(df_daily_plan, targets['df_foods'])
        else:
            df_daily_plan = pd.DataFrame()
            daily_totals = {'cal': 0, 'prot': 0.0, 'carbs': 0.0, 'fat': 0.0, 'fiber': 0.0, 'sodium': 0.0}

        st.session_state['final_plan_df'] = df_daily_plan[['Refeição', 'Alimento', 'Gramas']]
        st.session_state['final_totals'] = daily_totals
        
        # Função para determinar a cor do delta (feedback visual)
        def get_delta_color(current, target, is_max=False):
            if current == 0: return "off"
            if is_max: # Sódio (queremos <= target)
                return "inverse" if current > target else "normal"
            else: # Macros (queremos perto, mas delta positivo geralmente é "normal")
                return "normal" if current >= target * 0.9 else "inverse" # Avisa se estiver abaixo de 90% da meta

        col_c, col_p, col_ca, col_g, col_f, col_s = st.columns(6) 
        
        col_c.metric(
            "Calorias Totais", 
            f"{daily_totals['cal']:.0f} kcal", 
            delta=f"Meta: {targets['cal']}",
            delta_color=get_delta_color(daily_totals['cal'], targets['cal'])
        )
        col_p.metric(
            "Proteína Total", 
            f"{daily_totals['prot']:.1f} g", 
            delta=f"Meta: {targets['prot']}",
            delta_color=get_delta_color(daily_totals['prot'], targets['prot'])
        )
        col_ca.metric(
            "Carboidratos Total", 
            f"{daily_totals['carbs']:.1f} g", 
            delta=f"Meta: {targets['carbs']}",
            delta_color=get_delta_color(daily_totals['carbs'], targets['carbs'])
        )
        col_g.metric(
            "Gordura Total", 
            f"{daily_totals['fat']:.1f} g", 
            delta=f"Meta: {targets['fat']}",
            # Gordura geralmente tem um limite superior (max), mas vamos usar o alvo como referência
            delta_color=get_delta_color(daily_totals['fat'], targets['fat']) 
        )
        col_f.metric("Fibra Total", f"{daily_totals['fiber']:.1f} g", delta="Não Alvo")
        col_s.metric(
            "Sódio Total", 
            f"{daily_totals['sodium']:.0f} mg", 
            delta=f"Máximo: {targets['sodium']}",
            delta_color=get_delta_color(daily_totals['sodium'], targets['sodium'], is_max=True)
        ) 

        st.markdown("---")
        
        # Exibe o plano final para conferência
        st.subheader("Plano Detalhado (Para PDF)")
        df_display_final = st.session_state['final_plan_df'].copy()
        df_display_final['Gramas'] = df_display_final['Gramas'].astype(str) + ' g'
        st.dataframe(df_display_final, hide_index=True, use_container_width=True)
        
        col_pdf, _ = st.columns([0.4, 0.6])
        with col_pdf:
            st.download_button(
                label="Exportar Dieta Manual para PDF",
                data=generate_diet_pdf(st.session_state['username'], targets, st.session_state['final_plan_df'], st.session_state['final_totals']),
                file_name=f"Dieta_Manual_EveFii_{st.session_state['username']}_{datetime.now().strftime('%Y%m%d')}.pdf",
                mime="application/pdf",
                type="primary"
            )

def page_hidratacao_agua():
# ... (código da função) ...
    user_id = st.session_state['user_id']
    st.header("💧 Calculadora de Hidratação (Água)")
    st.info("Calcule a sua meta diária de ingestão de água com base no seu peso e idade. Lembre-se que é uma estimativa, consulte sempre um profissional.")
    
    profile = get_user_profile(user_id)
    df_metrics = get_body_metrics(user_id)
    
    initial_weight = df_metrics.iloc[0]['weight'] if not df_metrics.empty else 75.0
    initial_age = int(profile.get('age')) if profile and profile.get('age') else 30
    
    with st.form("agua_calc_form"):
        col1, col2 = st.columns(2)
        
        with col1:
            weight = st.number_input(
                "Peso Corporal (kg)", 
                min_value=30.0, 
                value=initial_weight, 
                format="%.1f",
                help="Preenchido com sua última avaliação."
            )
            age = st.number_input(
                "Sua Idade (anos)", 
                min_value=15, 
                value=initial_age
            )
        
        with col2:
            st.markdown("##### Ajustes Adicionais")
            activity_factor = st.slider(
                "Intensidade da Atividade Física", 
                min_value=0, max_value=2, value=0, step=1,
                format="Nível %d",
                help="Nível 0: Sedentário. Nível 1: Atividade Moderada (aumento de 500ml). Nível 2: Atividade Intensa (aumento de 1L)."
            )
            temp_factor = st.slider(
                "Temperatura/Clima",
                min_value=0, max_value=1, value=0, step=1,
                format="Nível %d",
                help="Nível 0: Normal. Nível 1: Clima Quente/Seco (aumento de 500ml)."
            )
            
        submitted = st.form_submit_button("Calcular Ingestão Ideal", type="primary")

    if submitted:
        base_liters, ml_per_kg = calculate_water_goal(weight, age)
        
        activity_adjustment = {0: 0.0, 1: 0.5, 2: 1.0}[activity_factor]
        temp_adjustment = {0: 0.0, 1: 0.5}[temp_factor]
        
        final_liters = base_liters + activity_adjustment + temp_adjustment
        
        st.subheader("✅ Sua Meta Diária de Hidratação")
        
        col_goal, col_info = st.columns(2)
        
        with col_goal:
            st.metric(
                "Meta Diária de Água", 
                f"{final_liters:.2f} Litros", 
                help=f"Base de {ml_per_kg} ml/kg + Ajustes."
            )
            
        with col_info:
            st.markdown(f"**Cálculo Base:** `{weight:.1f} kg x {ml_per_kg} ml/kg = {base_liters:.2f} L`")
            if activity_adjustment > 0:
                 st.markdown(f"**Ajuste por Atividade:** `+ {activity_adjustment:.2f} L`")
            if temp_adjustment > 0:
                 st.markdown(f"**Ajuste por Clima:** `+ {temp_adjustment:.2f} L`")
            st.markdown(f"**Total Ajustado:** `{final_liters:.2f} L`")

        st.markdown("---")
        
        st.subheader("Dicas de Consumo")
        hours_awake = 12 
        cups_of_water = math.ceil(final_liters / 0.250) 
        
        # Prevenção de divisão por zero e cálculo de minutos entre copos
        if final_liters > 0:
            minutes_per_cup = 60 / ((final_liters / hours_awake) / 0.250)
            st.success(f"Tente beber um copo de **250 ml** a cada **{minutes_per_cup:.0f} minutos** durante suas {hours_awake} horas de vigília, ou {cups_of_water} copos de 250ml no total.")
        else:
             st.info("Ajuste seu peso para ver as dicas de consumo.")

        st.markdown("---")
        
        st.subheader("📝 Monitoramento (Para o Seu Dia)")
        
        # Inicializa ou zera o contador de água se for um novo dia
        if 'agua_ingerida' not in st.session_state or st.session_state.get('agua_date') != datetime.now().date():
            st.session_state['agua_ingerida'] = 0.0
            st.session_state['agua_date'] = datetime.now().date()
            
        st.session_state['agua_meta_liters'] = final_liters 
        
        st.session_state['agua_ingerida'] = st.number_input(
            "Quantos Litros de Água Você Bebeu Hoje?", 
            min_value=0.0, 
            max_value=10.0, 
            value=st.session_state['agua_ingerida'], 
            step=0.1,
            key='agua_input' 
        )
        
        liters_input = st.session_state['agua_ingerida']
        
        if liters_input > 0:
            if liters_input < final_liters:
                st.warning(f"Faltam **{(final_liters - liters_input):.2f} Litros** para atingir sua meta diária de hidratação.")
            elif liters_input >= final_liters:
                st.balloons()
                st.success("🎉 **Meta de Hidratação Atingida!**")
        else:
            st.info("Insira o total de água consumido para monitorar seu progresso.")


def page_receitas():
# ... (código da função) ...
    user_id = st.session_state['user_id']
    st.header("🍚 Banco de Alimentos (TACO) - 100g")
    st.info(f"Gerencie seu banco de alimentos, **{st.session_state['username']}**. Fibra e Sódio são novos campos!")
    
    df_foods = get_all_foods(user_id) 
    
    st.subheader("1. Alimentos Cadastrados (por 100g)")
    if not df_foods.empty:
        df_display = df_foods.copy()
        df_display.columns = ['ID', 'Nome', 'Custo (R$)', 'Calorias (kcal)/100g', 'Proteína (g)/100g', 'Carbohidratos (g)/100g', 'Gordura (g)/100g', 'Fibra (g)/100g', 'Sódio (mg)/100g']
        st.dataframe(df_display[['ID', 'Nome', 'Calorias (kcal)/100g', 'Proteína (g)/100g', 'Carbohidratos (g)/100g', 'Gordura (g)/100g', 'Fibra (g)/100g', 'Sódio (mg)/100g']], hide_index=True)
        
        st.markdown("---")
        st.subheader("2. Editar ou Excluir Alimento")
        
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
                    fibra = st.number_input("Fibra (g) / 100g", min_value=0.0, format="%.1f", value=food_to_edit['fiber'])
                with col2:
                    carboidratos = st.number_input("Carbohidratos (g) / 100g", min_value=0.0, format="%.1f", value=food_to_edit['carbs'])
                    gordura = st.number_input("Gordura (g) / 100g", min_value=0.0, format="%.1f", value=food_to_edit['fat'])
                    sodium = st.number_input("Sódio (mg) / 100g", min_value=0.0, format="%.1f", value=food_to_edit['sodium']) 
                
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
                    if update_food(food_id_to_edit, nome, calorias, proteina, carboidratos, gordura, fibra, sodium): 
                        st.success(f"Alimento '{nome}' atualizado com sucesso!")
                        st.rerun()
                    else:
                        st.error(f"Erro: Não foi possível atualizar. O nome '{nome}' pode já existir para você.")
    else:
        st.info("Nenhum alimento cadastrado ainda.")
    
    st.markdown("---")
    
    st.subheader("3. Importar Alimentos via CSV")
    
    uploaded_file = st.file_uploader(
        "Selecione um arquivo CSV com alimentos (Colunas obrigatórias: **name**, **calories**, **protein**, **carbs**, **fat**. **fiber** e **sodium** são opcionais)", 
        type="csv"
    )
    
    if uploaded_file is not None:
        if st.button("Importar Alimentos do CSV", type="secondary"):
            count, error = import_foods_from_csv(user_id, uploaded_file)
            if error:
                st.error(f"❌ Erro na Importação: {error}")
            else:
                st.success(f"✅ Sucesso! **{count}** novos alimentos importados para **{st.session_state['username']}**.")
                st.balloons()
                st.rerun()
    
    st.markdown("---")

    st.subheader("4. Adicionar Novo Alimento Manualmente")
    with st.form("nova_receita"):
        nome = st.text_input("Nome do Alimento (Ex: Arroz Cozido)")
        col1, col2 = st.columns(2)
        with col1:
            calorias = st.number_input("Calorias (kcal) / 100g", min_value=0)
            proteina = st.number_input("Proteína (g) / 100g", min_value=0.0, format="%.1f")
            fibra = st.number_input("Fibra (g) / 100g", min_value=0.0, format="%.1f")
        with col2:
            carboidratos = st.number_input("Carbohidratos (g) / 100g", min_value=0.0, format="%.1f")
            gordura = st.number_input("Gordura (g) / 100g", min_value=0.0, format="%.1f")
            sodium = st.number_input("Sódio (mg) / 100g", min_value=0.0, format="%.1f", key='new_sodium') 
        
        submitted = st.form_submit_button("Salvar Novo Alimento", type="primary")
        if submitted and nome:
            if save_food(user_id, nome, calorias, proteina, carboidratos, gordura, fibra, sodium): 
                st.success(f"Alimento '{nome}' salvo com sucesso!")
                st.rerun()
            else:
                st.error(f"Erro: O alimento '{nome}' já existe para você. Por favor, use um nome diferente.")

def page_avaliacao_fisica():
# ... (código da função) ...
    user_id = st.session_state['user_id']
    st.header(f"🏋️ Avaliação Física e Composição Corporal - {st.session_state['username']}")
    st.info("Monitore sua composição corporal e registre sua foto de evolução.")
    
    df_metrics = get_body_metrics(user_id) 
    
    initial_values = {
        'weight': 75.0, 'height': 175.0, 'age': 30, 'neck': 38.0, 'waist': 80.0, 'hip': 95.0,
        'sk_chest': 10.0, 'sk_triceps': 10.0, 'sk_subscap': 15.0, 'sk_midax': 10.0, 'sk_supra': 15.0, 'sk_abdomen': 20.0, 'sk_thigh': 20.0
    }
    
    profile = get_user_profile(user_id)
    if profile:
        initial_values['height'] = profile['height']
        initial_values['age'] = profile['age']

    if not df_metrics.empty:
        last = df_metrics.iloc[0]
        initial_values['weight'] = last['weight']
        initial_values['waist'] = last['waist_circ']

    calculated_bf = None
    
    st.subheader("Registrar Nova Métrica e Foto")
    with st.form("new_metric"):
        date = st.date_input("Data da Avaliação", value=datetime.today())
        
        col_dados, col_medidas = st.columns(2)
        
        with col_dados:
            gender = st.selectbox("Gênero", ['Masculino', 'Feminino'], key='eval_gender', index=0 if profile is None or profile.get('gender')=='Masculino' else 1)
            weight = st.number_input("Peso (kg)", min_value=30.0, format="%.1f", value=initial_values['weight'])
            height = st.number_input("Altura (cm)", min_value=100.0, format="%.1f", value=initial_values['height'])
            age = st.number_input("Idade (anos)", min_value=15, value=initial_values['age'])
            
            save_user_profile(user_id, gender, height, age) 
            
            calc_method = st.radio(
                "Método de Cálculo de % Gordura", 
                ['Dobras Cutâneas (Jackson/Pollock 7)', 'Circunferências (Naval)'], 
                key='calc_method_radio'
            )
            
            st.markdown("---")
            uploaded_file = st.file_uploader("Foto de Evolução (Opcional)", type=['jpg', 'jpeg', 'png'])

        with col_medidas:
            st.markdown("##### Medidas Requeridas (cm ou mm)")
            waist = initial_values['waist']; hip = 0.0; neck = 0.0
            
            if calc_method == 'Circunferências (Naval)':
                st.info("Medidas em **cm**. Utilize fita métrica.")
                neck = st.number_input("Pescoço (cm)", min_value=25.0, format="%.1f", value=initial_values['neck'])
                waist = st.number_input("Cintura (cm)", min_value=50.0, format="%.1f", value=initial_values['waist'])
                if gender == 'Feminino':
                    hip = st.number_input("Quadril (cm)", min_value=70.0, format="%.1f", value=initial_values['hip'])
                
            else: 
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
                
                if st.form_submit_button("Salvar Métrica no Histórico", type="primary"):
                    date_str = date.strftime('%Y-%m-%d')
                    
                    photo_path = save_uploaded_photo(uploaded_file, user_id)
                    
                    if save_body_metric(user_id, date_str, weight, bf_val, st.session_state['waist_circ_save'], bmi_val, photo_path):
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
    
    st.subheader("Histórico de Composição Corporal")
    df_metrics = get_body_metrics(user_id)
    
    if df_metrics.empty:
        st.info(f"Nenhuma métrica registrada ainda para {st.session_state['username']}.")
        return

    last_metric = df_metrics.iloc[0]
    st.markdown(f"##### Última Avaliação ({last_metric['date'].strftime('%d/%m/%Y')}):")
    
    col_w, col_bf, col_mg, col_mm, col_bmi = st.columns(5)
    col_w.metric("Peso", f"{last_metric['weight']:.1f} kg")
    col_bf.metric("Gordura", f"{last_metric['body_fat_perc']:.1f} %")
    col_mg.metric("Massa Gorda", f"{last_metric['Massa Gorda (kg)']:.1f} kg")
    col_mm.metric("Massa Magra", f"{last_metric['Massa Magra (kg)']:.1f} kg")
    col_bmi.metric("IMC", f"{last_metric['bmi']:.1f}")
    
    st.markdown("---")

    df_metrics = df_metrics.sort_values(by='date')
    st.line_chart(df_metrics, x='date', y=['weight', 'Massa Magra (kg)', 'Massa Gorda (kg)'])
    st.line_chart(df_metrics, x='date', y=['body_fat_perc', 'bmi'])

def page_relatorios():
# ... (código da função) ...
    user_id = st.session_state['user_id']
    st.header(f"📊 Relatório de Evolução e Análise - {st.session_state['username']}")
    
    df_metrics = get_body_metrics(user_id)
    df_foods = get_all_foods(user_id) 
    
    st.subheader("1. Evolução de Métricas Corporais")
    if df_metrics.empty:
        st.warning("Cadastre métricas corporais para visualizar o relatório de evolução.")
    elif len(df_metrics) < 2:
        st.info(f"Você tem apenas **{len(df_metrics)}** avaliação. Duas ou mais avaliações são necessárias para calcular a evolução.")
        last_metric = df_metrics.iloc[0]
        st.markdown(f"**Avaliação Registrada:** {last_metric['date'].strftime('%d/%m/%Y')}")
    else:
        df_metrics_chrono = df_metrics.sort_values(by='date')
        first = df_metrics_chrono.iloc[0]
        last = df_metrics_chrono.iloc[-1]
        
        st.markdown(f"**Análise da Evolução:** {first['date'].strftime('%d/%m/%Y')} a {last['date'].strftime('%d/%m/%Y')}")
        
        col_w, col_bf, col_mm, col_mg = st.columns(4)
        
        def display_evolution(col, metric_name, start_val, end_val, unit):
            diff = end_val - start_val
            diff_str = f"{'+' if diff > 0 else ''}{diff:.1f} {unit}"
            
            if (metric_name in ['Peso', '% Gordura', 'Massa Gorda'] and diff < 0) or \
               (metric_name == 'Massa Magra' and diff > 0):
                delta_color = "inverse" if diff < 0 else "normal"
            elif diff != 0:
                delta_color = "normal" if diff > 0 else "inverse"
            else:
                delta_color = "off"

            col.metric(
                metric_name, 
                f"{end_val:.1f} {unit}", 
                delta=diff_str, 
                delta_color=delta_color if diff != 0 else "off"
            )

        display_evolution(col_w, 'Peso', first['weight'], last['weight'], 'kg')
        display_evolution(col_bf, '% Gordura', first['body_fat_perc'], last['body_fat_perc'], '%')
        display_evolution(col_mg, 'Massa Gorda', first['Massa Gorda (kg)'], last['Massa Gorda (kg)'], 'kg')
        display_evolution(col_mm, 'Massa Magra', first['Massa Magra (kg)'], last['Massa Magra (kg)'], 'kg')
        
        st.markdown("---")
        
        st.download_button(
            label="Exportar Relatório de Evolução para PDF",
            data=generate_metrics_pdf(st.session_state['username'], df_metrics),
            file_name=f"Evolucao_EveFii_{st.session_state['username']}_{datetime.now().strftime('%Y%m%d')}.pdf",
            mime="application/pdf",
            type="primary"
        )
    
    st.markdown("---")
    
    st.subheader("2. Galeria de Fotos de Evolução")
    
    photos = df_metrics[df_metrics['photo_path'].notnull()].sort_values(by='date', ascending=True)
    
    if photos.empty:
        st.info("Nenhuma foto de evolução registrada ainda. Registre uma na página 'Avaliação Física'.")
    else:
        st.caption("Clique nas fotos para ampliar. (As fotos serão exibidas em ordem cronológica)")
        photo_cols = st.columns(min(len(photos), 5)) 
        
        for i, row in photos.iterrows():
            if row['photo_path']:
                file_path = os.path.join(PHOTOS_DIR, row['photo_path'])
                
                try:
                    with photo_cols[i % 5]:
                        st.image(file_path, caption=row['date'].strftime('%d/%m/%Y'), use_column_width=True)
                except Exception:
                    with photo_cols[i % 5]:
                        st.warning("Foto não disponível (Path Incorreto ou Restrito)")

    st.markdown("---")

    st.subheader("3. Análise da Dieta Otimizada (Metas vs. Otimizado)")
    
    if 'targets' in st.session_state and 'final_totals' in st.session_state:
        targets = st.session_state['targets']
        finals = st.session_state['final_totals']
        
        data = {
            'Macro/Micronutriente': ['Calorias', 'Proteína', 'Carboidratos', 'Gordura', 'Fibra', 'Sódio'], 
            'Meta': [targets['cal'], targets['prot'], targets['carbs'], targets['fat'], 0, targets['sodium']], 
            'Otimizado': [finals['cal'], finals['prot'], finals['carbs'], finals['fat'], finals['fiber'], finals['sodium']], 
            'Unidade': ['kcal', 'g', 'g', 'g', 'g', 'mg']
        }
        df_comparison = pd.DataFrame(data).set_index('Macro/Micronutriente')
        
        st.dataframe(df_comparison, use_container_width=True)

        df_plot = df_comparison.iloc[0:4][['Meta', 'Otimizado']].copy() 
        fig, ax = plt.subplots(figsize=(8, 4))
        df_plot.plot(kind='bar', ax=ax, rot=0)
        ax.set_title('Comparação: Metas Diárias vs. Plano Manual (Macros)')
        ax.set_ylabel('Valor (kcal/g)')
        ax.legend(loc='upper right')
        plt.tight_layout()
        st.pyplot(fig)
        
        st.markdown(f"**Sódio Total Manual:** {finals['sodium']:.0f} mg (Limite Máximo: {targets['sodium']} mg)")

    else:
        st.info("Gere um plano de dieta na página 'Planejador Manual' para visualizar esta análise.")
        
    st.markdown("---")
    st.subheader("4. Distribuição de Nutrientes (Banco de Alimentos)")
    
    if df_foods.empty:
        st.warning("Cadastre alimentos para visualizar a análise.")
    else:
        total_prot = df_foods['protein'].sum()
        total_carbs = df_foods['carbs'].sum()
        total_fat = df_foods['fat'].sum()
        total_fiber = df_foods['fiber'].sum()
        total_sodium = df_foods['sodium'].sum() 
        
        data = [total_prot, total_carbs, total_fat, total_fiber] 
        labels = ['Proteína (g)', 'Carboidratos (g)', 'Gordura (g)', 'Fibra (g)'] 
        
        fig, ax = plt.subplots()
        ax.pie(data, labels=labels, autopct='%1.1f%%', startangle=90, colors=['#4CAF50', '#2196F3', '#FFC107', '#9E9E9E']) 
        ax.axis('equal') 
        ax.set_title('Distribuição Total dos Nutrientes (Por 100g de Alimento)')
        
        st.pyplot(fig)
        
        st.markdown(f"**Sódio Total no Banco:** {total_sodium:.0f} mg")

# --- Login e Roteamento Principal ---

def main_app():
# ... (código da função) ...
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
        "Planejador Manual": page_planejador_inteligente, # Nome Alterado
        "Avaliação Física": page_avaliacao_fisica,
        "Banco de Alimentos (TACO)": page_receitas, 
        "💧 Hidratação (Água)": page_hidratacao_agua,
        "Relatório de Evolução": page_relatorios
    }

    st.sidebar.title("EveFii v17 - Completo")
    selection = st.sidebar.radio("Navegação", list(PAGES.keys()))
    
    st.sidebar.markdown("---")
    if st.sidebar.button("Logout", type="secondary"):
        st.session_state['logged_in'] = False
        st.session_state.pop('username', None)
        st.session_state.pop('user_id', None)
        st.session_state.pop('targets', None)
        st.session_state.pop('final_plan_df', None)
        st.session_state.pop('final_totals', None)
        st.session_state.pop('manual_plan', None) # Nova chave a limpar
        st.rerun()

    PAGES[selection]()

def show_login():
# ... (código da função) ...
    st.title("EveFii v17 — Suporte Multiusuário")
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
                    st.session_state['user_id'] = get_user_id(username)
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
    
    st.set_page_config(page_title="EveFii v17 Nutrição", layout="wide")
    
    init_db()
    
    os.makedirs(PHOTOS_DIR, exist_ok=True)
    
    if 'logged_in' not in st.session_state:
        st.session_state['logged_in'] = False

    if st.session_state['logged_in']:
        main_app()
    else:
        show_login()
