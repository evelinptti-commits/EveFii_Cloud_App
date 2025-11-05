# EveFii_v4_app.py - Versão FINAL para Streamlit Cloud

# Imports
import streamlit as st
import sqlite3
import hashlib
import os
import pandas as pd
from datetime import datetime
from fpdf import FPDF
from pulp import LpProblem, LpMaximize, LpVariable, PULP_CBC_CMD 
# As bibliotecas 'python-docx' e 'openpyxl' estão nas requirements, mas não são usadas no código.

# --- Configuração e Funções de Utilitário ---
DB_PATH = "evefii_v4.db"
PHOTOS_DIR = "photos" 

# 1. Conexão e Inicialização do Banco de Dados usando Caching (Melhor Prática)
@st.cache_resource
def init_db():
    # Esta função roda apenas uma vez para toda a vida do aplicativo
    conn = sqlite3.connect(DB_PATH) 
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    # Cria a tabela de usuários se não existir
    cur.execute('CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE, password_hash TEXT)')
    
    # Adiciona usuário padrão se o banco estiver vazio
    cur.execute("SELECT COUNT(*) FROM users"); c = cur.fetchone()[0]
    if c == 0:
        pw = hashlib.sha256('change-me'.encode()).hexdigest()
        cur.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)", ('eve', pw))
    
    conn.commit()
    conn.close()

# 2. Funções de Criptografia e Verificação
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def verify_user(username, password):
    conn = sqlite3.connect(DB_PATH) 
    cur = conn.cursor()
    cur.execute("SELECT password_hash FROM users WHERE username = ?", (username,))
    user = cur.fetchone()
    conn.close()
    if user:
        return user[0] == hash_password(password)
    return False

# --- Estrutura das Páginas do Aplicativo Completo ---

def page_planejador_inteligente():
    st.header("🧠 Planejador Inteligente de Refeições (Otimização PuLP)")
    st.info("Aqui é onde o algoritmo de otimização PuLP irá rodar para criar o plano de refeições mais eficiente.")
    
    st.subheader("Simulação de Otimização")
    # Botão primário para destaque
    if st.button("Executar Otimização", type="primary"): 
        with st.spinner("Otimizando plano de refeições..."):
            # Exemplo de problema PuLP
            prob = LpProblem("Problema_Simples", LpMaximize)
            x = LpVariable("Variável_1", 0, 4)
            y = LpVariable("Variável_2", -1, 1)
            prob += x + y, "Função_Objetivo"
            prob += 2*x + y <= 8, "Restrição_1"
            
            # Otimização
            prob.solve(PULP_CBC_CMD()) 
            
            if prob.status == 1:
                st.balloons() # Efeito de sucesso
                st.success(f"Otimização concluída com sucesso! Resultado PuLP: {prob.objective.value()}.")
                st.write(f"Variável X: {x.varValue}, Variável Y: {y.varValue}")
                st.write("Esta seção seria preenchida com o plano de refeições otimizado.")
            else:
                st.error("Erro na otimização. Verifique as restrições.")

def page_receitas():
    st.header("🍳 Gestão de Receitas e Cardápios")
    st.write("Esta página permite adicionar, editar e visualizar as receitas usadas no planejamento.")
    
    # Exemplo de visualização
    data = {
        'Nome': ['Salmão Grelhado', 'Salada Caesar', 'Omelete de Legumes'],
        'Custo Estimado (R$)': [15.00, 8.50, 6.00],
        'Calorias Estimadas': [350, 280, 220]
    }
    df = pd.DataFrame(data)
    st.dataframe(df)

    st.markdown("---")
    st.subheader("Adicionar Nova Receita")
    with st.form("nova_receita"):
        nome = st.text_input("Nome da Receita")
        custo = st.number_input("Custo Estimado (R$)", min_value=0.0)
        calorias = st.number_input("Calorias", min_value=0)
        submitted = st.form_submit_button("Salvar Receita", type="primary")
        if submitted:
            st.success(f"Receita '{nome}' salva com sucesso!")

def page_inventario():
    st.header("📦 Inventário e Lista de Compras")
    st.write("Gerencie o que você tem em estoque para otimizar suas compras.")

def page_relatorios():
    st.header("📊 Relatórios e Análise de Custos")
    st.write("Visualize gráficos de custo médio por dia, desperdício e nutrientes.")

# --- Login e Roteamento Principal ---

def main_app():
    # Exibe o usuário logado na sidebar
    st.sidebar.markdown(f"**Usuário Logado:** `{st.session_state.get('username', 'N/A')}`")
    st.sidebar.markdown("---")
    
    PAGES = {
        "Planejador Inteligente": page_planejador_inteligente,
        "Gestão de Receitas": page_receitas,
        "Inventário": page_inventario,
        "Relatórios": page_relatorios
    }

    st.sidebar.title("EveFii v3 Completo")
    selection = st.sidebar.radio("Navegação", list(PAGES.keys()))
    
    st.sidebar.markdown("---")
    if st.sidebar.button("Logout", type="secondary"):
        st.session_state['logged_in'] = False
        st.session_state.pop('username', None)
        st.rerun()

    PAGES[selection]()

def show_login():
    st.title("EveFii v3 — Versão Completa e Inteligente")
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
    
    st.set_page_config(page_title="EveFii v3 Completo", layout="wide")
    
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
