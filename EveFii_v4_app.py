# EveFii_v4_app.py - Versão FINAL, Completa e Funcional para Streamlit Cloud (Prioridade: Saúde)

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

# 1. Conexão do Banco de Dados
def get_conn():
    # Adicionando check_same_thread=False para compatibilidade com Streamlit
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

# 2. Inicialização do Banco de Dados (Cria as 3 Tabelas Cruciais)
@st.cache_resource
def init_db():
    conn = get_conn(); cur = conn.cursor()
    
    # Tabela 1: Usuários (Login)
    cur.execute('CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE, password_hash TEXT)')
    
    # Tabela 2: Receitas (Dados de Custo e Nutrição - ESSENCIAL)
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
    
    # Tabela 3: Inventário
    cur.execute('''
        CREATE TABLE IF NOT EXISTS inventory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item TEXT UNIQUE,
            quantity REAL,
            unit TEXT
        )
    ''')
    
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

# 4. Funções de Receitas
def save_recipe(name, cost, cal, prot, carb, fat):
    conn = get_conn(); cur = conn.cursor()
    try:
        cur.execute("INSERT INTO recipes (name, cost, calories, protein, carbs, fat) VALUES (?, ?, ?, ?, ?, ?)", 
                    (name, cost, cal, prot, carb, fat))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def get_all_recipes():
    conn = get_conn(); 
    recipes = pd.read_sql("SELECT id, name, cost, calories, protein, carbs, fat FROM recipes", conn)
    conn.close()
    return recipes

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

# --- Estrutura das Páginas do Aplicativo (Lógica Real) ---

def page_planejador_inteligente():
    st.header("🧠 Planejador Inteligente de Refeições (Prioridade: Metas de Saúde)")
    st.info("Otimize seu plano de refeições para ATINGIR suas metas nutricionais, mantendo o custo como restrição.")
    
    df_recipes = get_all_recipes()
    
    if df_recipes.empty:
        st.warning("🚨 Por favor, cadastre receitas na página 'Gestão de Receitas' antes de otimizar.")
        return

    # --- Definição de Metas (Interface) ---
    st.subheader("1. Definição de Metas")
    
    with st.form("metas_form"):
        st.markdown("**Metas Nutricionais (Por Dia, o que um nutricionista recomendaria)**")
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            target_cal = st.number_input("Calorias Alvo (kcal)", min_value=1200, value=2000)
        with col2:
            target_prot = st.number_input("Proteína Alvo (g)", min_value=50, value=80)
        with col3:
            target_carbs = st.number_input("Carbohidratos Alvo (g)", min_value=100, value=250)
        with col4:
            target_fat = st.number_input("Gordura Alvo (g)", min_value=30, value=60)
        
        st.markdown("---")
        colA, colB = st.columns(2)
        with colA:
            max_cost = st.number_input("Custo Máximo do Plano (R$)", min_value=10.0, value=200.0, format="%.2f")
        with colB:
            num_days = st.number_input("Número de Dias no Plano", min_value=1, max_value=7, value=3)

        submitted = st.form_submit_button("Gerar Plano de Saúde Otimizado", type="primary")

    if submitted:
        # --- LÓGICA DE OTIMIZAÇÃO (FOCO NA META) ---
        recipes = df_recipes['name'].tolist()
        
        # Alvos Totais para o período:
        total_target_cal = target_cal * num_days
        total_target_prot = target_prot * num_days
        total_target_carbs = target_carbs * num_days
        total_target_fat = target_fat * num_days

        # Variáveis de Decisão: Número de vezes que cada receita será usada
        recipe_vars = LpVariable.dicts("Receita", recipes, 0, None, cat='Integer')

        # O problema: MINIMIZAR o desvio das Calorias (o mais importante para uma dieta)
        prob = LpProblem("Otimizacao_Saude_EveFii", LpMinimize)
        
        # Variáveis de Desvio (Penalty): Medem o quão longe estamos da meta de calorias
        dev_cal_pos = LpVariable("Desvio_Calorias_Pos", 0) # Desvio positivo
        dev_cal_neg = LpVariable("Desvio_Calorias_Neg", 0) # Desvio negativo

        # Restrição 1: A soma das calorias deve ser igual ao alvo, mais os desvios
        # Soma_Calorias + Desvio_Negativo - Desvio_Positivo = Meta_Calorica_Total
        prob += lpSum(df_recipes.loc[df_recipes['name'] == r, 'calories'].iloc[0] * recipe_vars[r] for r in recipes) + dev_cal_neg - dev_cal_pos == total_target_cal, "Restricao_Calorias"
        
        # Função Objetivo: Minimizar os desvios (Foco de um nutricionista)
        prob += dev_cal_pos + dev_cal_neg, "Minimizar_Desvio_Calorico"

        # Restrição 2: Custo Máximo (Restrição secundária)
        total_cost_expr = lpSum(df_recipes.loc[df_recipes['name'] == r, 'cost'].iloc[0] * recipe_vars[r] for r in recipes)
        prob += total_cost_expr <= max_cost, "Restricao_Custo_Maximo"
        
        # Restrição 3: Restrições de Nutrientes (As outras metas devem ser atendidas minimamente)
        # 90% da meta de Proteína e Carbos
        prob += lpSum(df_recipes.loc[df_recipes['name'] == r, 'protein'].iloc[0] * recipe_vars[r] for r in recipes) >= total_target_prot * 0.9, "Restricao_Proteina_Min"
        prob += lpSum(df_recipes.loc[df_recipes['name'] == r, 'carbs'].iloc[0] * recipe_vars[r] for r in recipes) >= total_target_carbs * 0.9, "Restricao_Carbos_Min"
        # 110% da meta de Gordura (limite superior)
        prob += lpSum(df_recipes.loc[df_recipes['name'] == r, 'fat'].iloc[0] * recipe_vars[r] for r in recipes) <= total_target_fat * 1.1, "Restricao_Gordura_Max"


        # Resolvendo o Problema
        with st.spinner("Resolvendo plano nutricional..."):
            prob.solve(PULP_CBC_CMD())
        
        # --- Visualização de Resultados ---
        st.subheader("2. Resultado do Plano Otimizado")
        
        if LpStatus[prob.status] == "Optimal":
            st.balloons()
            st.success("✅ Plano de dieta otimizado encontrado! Metas nutricionais atendidas.")
            
            final_cost = value(total_cost_expr)
            final_cal = value(lpSum(df_recipes.loc[df_recipes['name'] == r, 'calories'].iloc[0] * recipe_vars[r] for r in recipes))
            
            st.metric("Custo Total do Plano", f"R$ {final_cost:.2f}")
            st.metric("Calorias Totais no Plano", f"{final_cal:.0f} kcal (Alvo: {total_target_cal} kcal)")

            # Tabela de Resultados
            plan_data = []
            for v in prob.variables():
                if v.varValue > 0 and "Receita" in v.name:
                    recipe_name = v.name.replace('Receita_', '').replace('_', ' ')
                    plan_data.append({
                        'Receita': recipe_name,
                        'Quantidade (vezes)': int(v.varValue),
                    })
            
            if plan_data:
                st.subheader("Cardápio Recomendado:")
                st.dataframe(pd.DataFrame(plan_data), hide_index=True)
            else:
                st.warning("Plano otimizado, mas não foi possível encontrar um plano viável com as restrições de custo e nutrição.")

        else:
            st.error(f"❌ Otimização Falhou. Status: {LpStatus[prob.status]}. Não foi possível atingir as metas. Tente aumentar o custo ou reduzir as metas de nutrientes.")

def page_receitas():
    st.header("🍳 Gestão de Receitas e Cardápios")

    # --- Formulário de Cadastro ---
    st.subheader("Adicionar Nova Receita")
    with st.form("nova_receita"):
        nome = st.text_input("Nome da Receita")
        
        col1, col2 = st.columns(2)
        with col1:
            custo = st.number_input("Custo Estimado (R$)", min_value=0.0, format="%.2f")
            calorias = st.number_input("Calorias Totais (kcal)", min_value=0)
        with col2:
            proteina = st.number_input("Proteína (g)", min_value=0.0, format="%.1f")
            carboidratos = st.number_input("Carbohidratos (g)", min_value=0.0, format="%.1f")
            gordura = st.number_input("Gordura (g)", min_value=0.0, format="%.1f")
        
        submitted = st.form_submit_button("Salvar Receita", type="primary")
        if submitted and nome:
            if save_recipe(nome, custo, calorias, proteina, carboidratos, gordura):
                st.success(f"Receita '{nome}' salva com sucesso!")
            else:
                st.error(f"Erro: A receita '{nome}' já existe. Por favor, use um nome diferente.")
    
    st.markdown("---")

    # --- Visualização das Receitas Salvas ---
    st.subheader("Receitas Cadastradas")
    df_recipes = get_all_recipes()
    if not df_recipes.empty:
        # Renomear colunas para melhor visualização
        df_recipes.columns = ['ID', 'Nome', 'Custo (R$)', 'Calorias (kcal)', 'Proteína (g)', 'Carbohidratos (g)', 'Gordura (g)']
        st.dataframe(df_recipes.drop(columns=['ID']), hide_index=True)
    else:
        st.info("Nenhuma receita cadastrada ainda. Adicione algumas acima para que o Planejador funcione!")

def page_inventario():
    st.header("📦 Inventário e Lista de Compras")
    st.info("Gerencie o que você tem em estoque. A otimização futura usará estes dados para gerar a lista de compras.")
    
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
    st.header("📊 Relatórios e Análise de Custos")
    st.info("Visualize os custos e a distribuição de nutrientes dos seus planos de refeições.")
    
    # Exemplo de Relatório: Gráfico de Custos
    st.subheader("Análise de Custo por Receita")
    
    df_recipes = get_all_recipes()
    
    if df_recipes.empty:
        st.warning("
