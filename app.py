
import streamlit as st
from supabase import create_client
from datetime import date, datetime
from decimal import Decimal
import uuid
import pandas as pd
from relatorios import gerar_pdf_gastos

st.set_page_config(
    page_title="Planejar Serviços e Notas",
    page_icon="🌱",
    layout="wide"
)

# -----------------------------
# Conexão Supabase
# -----------------------------
def get_supabase():
    # Um cliente Supabase por sessão do Streamlit.
    # Isso evita compartilhar autenticação entre usuários diferentes.
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_ANON_KEY"]
    client = create_client(url, key)

    access_token = st.session_state.get("access_token")
    refresh_token = st.session_state.get("refresh_token")
    if access_token and refresh_token:
        try:
            session = client.auth.set_session(access_token, refresh_token)
            if session and session.session:
                st.session_state["access_token"] = session.session.access_token
                st.session_state["refresh_token"] = session.session.refresh_token
        except Exception:
            st.session_state.pop("user", None)
            st.session_state.pop("access_token", None)
            st.session_state.pop("refresh_token", None)
    return client

supabase = get_supabase()

def brl(v):
    try:
        return f"R$ {float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except:
        return "R$ 0,00"

def login(email, senha):
    try:
        resp = supabase.auth.sign_in_with_password({"email": email, "password": senha})
        if not resp.user:
            return False, "Usuário ou senha inválidos."
        st.session_state["user"] = {
            "id": resp.user.id,
            "email": resp.user.email,
        }
        if resp.session:
            st.session_state["access_token"] = resp.session.access_token
            st.session_state["refresh_token"] = resp.session.refresh_token
        return True, None
    except Exception as e:
        return False, f"Não foi possível entrar: {e}"

def logout():
    try:
        supabase.auth.sign_out()
    except:
        pass
    st.session_state.clear()
    st.rerun()

def get_profile():
    uid = st.session_state["user"]["id"]
    try:
        r = supabase.table("profiles").select("*").eq("id", uid).single().execute()
        return r.data
    except:
        return None

def require_login():
    if "user" in st.session_state:
        return
    st.title("🌱 Planejar Serviços e Notas")
    st.caption("Acesso da equipe")
    with st.form("login"):
        email = st.text_input("E-mail")
        senha = st.text_input("Senha", type="password")
        entrar = st.form_submit_button("Entrar", use_container_width=True)
    if entrar:
        ok, err = login(email, senha)
        if ok:
            st.rerun()
        else:
            st.error(err)
    st.stop()

require_login()
profile = get_profile()
if not profile:
    st.error("Seu usuário ainda não possui perfil no sistema. Peça ao administrador para cadastrá-lo na tabela profiles.")
    if st.button("Sair"):
        logout()
    st.stop()

is_admin = profile.get("role") == "admin"
nome_usuario = profile.get("nome") or st.session_state["user"]["email"]

# -----------------------------
# Sidebar
# -----------------------------
st.sidebar.title("🌱 Planejar")
st.sidebar.write(f"**{nome_usuario}**")
st.sidebar.caption("Administrador" if is_admin else "Equipe")

menu_items = ["🏠 Início", "🛠️ Adicionar serviço", "🧾 Adicionar nota", "📋 Meus lançamentos"]
if is_admin:
    menu_items += ["📊 Painel administrativo", "✅ Conferir notas", "👥 Equipe"]

menu = st.sidebar.radio("Menu", menu_items)
st.sidebar.divider()
if st.sidebar.button("Sair", use_container_width=True):
    logout()

# -----------------------------
# Home
# -----------------------------
if menu == "🏠 Início":
    st.title("Planejar Serviços e Notas")
    st.write("Sistema online para a equipe lançar serviços e notas pelo celular ou computador.")

    c1, c2 = st.columns(2)
    with c1:
        st.info("🛠️ **Serviços**\n\nRegistre rapidamente o serviço executado, cliente, fazenda, área e observações.")
    with c2:
        st.info("🧾 **Notas**\n\nEnvie foto/PDF da nota, fornecedor, valor, categoria e dados relacionados.")

    st.subheader("Atalhos")
    a, b = st.columns(2)
    with a:
        if st.button("➕ Novo serviço", use_container_width=True):
            st.session_state["go_menu"] = "🛠️ Adicionar serviço"
            st.rerun()
    with b:
        if st.button("➕ Nova nota", use_container_width=True):
            st.session_state["go_menu"] = "🧾 Adicionar nota"
            st.rerun()

# Workaround simple navigation via session state
if "go_menu" in st.session_state:
    target = st.session_state.pop("go_menu")
    st.warning(f"Abra **{target}** no menu lateral.")

# -----------------------------
# Adicionar serviço
# -----------------------------
elif menu == "🛠️ Adicionar serviço":
    st.title("🛠️ Adicionar serviço")
    with st.form("servico_form", clear_on_submit=True):
        c1, c2 = st.columns(2)
        with c1:
            data_servico = st.date_input("Data do serviço", value=date.today())
            cliente = st.text_input("Cliente / Produtor *")
            fazenda = st.text_input("Fazenda")
            tipo = st.selectbox("Tipo de serviço *", [
                "Coleta de solo",
                "Agricultura de precisão",
                "Carbono / Sensoriamento de carbono",
                "Mapeamento",
                "Regulagem de máquina",
                "Visita técnica",
                "Laudo",
                "Outro"
            ])
        with c2:
            area = st.number_input("Área (ha)", min_value=0.0, step=0.01)
            valor = st.number_input("Valor do serviço (R$)", min_value=0.0, step=10.0)
            status = st.selectbox("Status", ["Executado", "Em andamento", "Agendado"])
            observacao = st.text_area("Observação")

        salvar = st.form_submit_button("💾 Salvar serviço", use_container_width=True)

    if salvar:
        if not cliente.strip():
            st.error("Informe o cliente/produtor.")
        else:
            payload = {
                "usuario_id": st.session_state["user"]["id"],
                "data_servico": str(data_servico),
                "cliente": cliente.strip(),
                "fazenda": fazenda.strip() or None,
                "tipo_servico": tipo,
                "area_ha": float(area),
                "valor": float(valor),
                "status": status,
                "observacao": observacao.strip() or None,
            }
            try:
                supabase.table("servicos").insert(payload).execute()
                st.success("Serviço salvo com sucesso.")
            except Exception as e:
                st.error(f"Erro ao salvar: {e}")

# -----------------------------
# Adicionar nota
# -----------------------------
elif menu == "🧾 Adicionar nota":
    st.title("🧾 Adicionar nota")
    st.caption("Você pode enviar uma foto ou PDF do comprovante.")

    with st.form("nota_form", clear_on_submit=True):
        arquivo = st.file_uploader("Foto/PDF da nota *", type=["jpg", "jpeg", "png", "pdf"])
        c1, c2 = st.columns(2)
        with c1:
            data_nota = st.date_input("Data da nota", value=date.today())
            fornecedor = st.text_input("Fornecedor *")
            valor_nota = st.number_input("Valor (R$) *", min_value=0.0, step=1.0)
            categoria = st.selectbox("Categoria", [
                "Combustível",
                "Manutenção",
                "Peças",
                "Alimentação",
                "Hospedagem",
                "Pedágio",
                "Material de escritório",
                "Campo / Coleta",
                "Carbono",
                "Outros"
            ])
        with c2:
            cliente_nota = st.text_input("Cliente / Produtor relacionado")
            fazenda_nota = st.text_input("Fazenda relacionada")
            forma_pagamento = st.selectbox("Forma de pagamento", [
                "Pix", "Cartão", "Dinheiro", "Boleto", "Transferência", "Outro"
            ])
            observacao_nota = st.text_area("Observação")

        enviar = st.form_submit_button("📤 Enviar nota", use_container_width=True)

    if enviar:
        if not arquivo:
            st.error("Anexe a foto ou PDF da nota.")
        elif not fornecedor.strip():
            st.error("Informe o fornecedor.")
        elif valor_nota <= 0:
            st.error("Informe um valor maior que zero.")
        else:
            try:
                ext = arquivo.name.split(".")[-1].lower()
                uid = st.session_state["user"]["id"]
                nome_arquivo = f"{uid}/{datetime.now().strftime('%Y/%m')}/{uuid.uuid4().hex}.{ext}"
                conteudo = arquivo.getvalue()
                supabase.storage.from_("notas").upload(
                    nome_arquivo,
                    conteudo,
                    {"content-type": arquivo.type or "application/octet-stream", "upsert": "false"}
                )

                payload = {
                    "usuario_id": uid,
                    "data_nota": str(data_nota),
                    "fornecedor": fornecedor.strip(),
                    "valor": float(valor_nota),
                    "categoria": categoria,
                    "cliente": cliente_nota.strip() or None,
                    "fazenda": fazenda_nota.strip() or None,
                    "forma_pagamento": forma_pagamento,
                    "observacao": observacao_nota.strip() or None,
                    "arquivo_path": nome_arquivo,
                    "arquivo_nome_original": arquivo.name,
                    "status": "Pendente"
                }
                supabase.table("notas").insert(payload).execute()
                st.success("Nota enviada. Ela ficou como **Pendente de conferência**.")
            except Exception as e:
                st.error(f"Erro ao enviar a nota: {e}")

# -----------------------------
# Meus lançamentos
# -----------------------------
elif menu == "📋 Meus lançamentos":
    st.title("📋 Meus lançamentos")
    uid = st.session_state["user"]["id"]
    tab1, tab2 = st.tabs(["Serviços", "Notas"])

    with tab1:
        try:
            r = supabase.table("servicos").select("*").eq("usuario_id", uid).order("created_at", desc=True).execute()
            df = pd.DataFrame(r.data or [])
            if df.empty:
                st.info("Nenhum serviço lançado ainda.")
            else:
                cols = [c for c in ["data_servico","cliente","fazenda","tipo_servico","area_ha","valor","status"] if c in df.columns]
                st.dataframe(df[cols], use_container_width=True, hide_index=True)
        except Exception as e:
            st.error(f"Erro ao carregar serviços: {e}")

    with tab2:
        try:
            r = supabase.table("notas").select("*").eq("usuario_id", uid).order("created_at", desc=True).execute()
            df = pd.DataFrame(r.data or [])
            if df.empty:
                st.info("Nenhuma nota lançada ainda.")
            else:
                cols = [c for c in ["data_nota","fornecedor","valor","categoria","cliente","fazenda","status"] if c in df.columns]
                st.dataframe(df[cols], use_container_width=True, hide_index=True)
        except Exception as e:
            st.error(f"Erro ao carregar notas: {e}")

# -----------------------------
# Painel admin
# -----------------------------
elif menu == "📊 Painel administrativo" and is_admin:
    st.title("📊 Painel administrativo")
    st.caption("Visão geral dos gastos e serviços da Planejar, com filtros e relatório em PDF.")
    try:
        rs = supabase.table("servicos").select("*").order("created_at", desc=True).execute()
        rn = supabase.table("notas").select("*").order("created_at", desc=True).execute()
        rp = supabase.table("profiles").select("id,nome").execute()

        servicos = pd.DataFrame(rs.data or [])
        notas = pd.DataFrame(rn.data or [])
        perfis = pd.DataFrame(rp.data or [])

        mapa_nomes = {}
        if not perfis.empty and "id" in perfis.columns and "nome" in perfis.columns:
            mapa_nomes = dict(zip(perfis["id"], perfis["nome"]))

        if not notas.empty:
            notas["responsavel"] = notas["usuario_id"].map(mapa_nomes).fillna("Não identificado")
            notas["valor"] = pd.to_numeric(notas["valor"], errors="coerce").fillna(0.0)
            notas["data_nota_dt"] = pd.to_datetime(notas["data_nota"], errors="coerce")

        if not servicos.empty:
            servicos["responsavel"] = servicos["usuario_id"].map(mapa_nomes).fillna("Não identificado")
            servicos["valor"] = pd.to_numeric(servicos["valor"], errors="coerce").fillna(0.0)
            servicos["area_ha"] = pd.to_numeric(servicos["area_ha"], errors="coerce").fillna(0.0)
            servicos["data_servico_dt"] = pd.to_datetime(servicos["data_servico"], errors="coerce")

        tab_gastos, tab_servicos = st.tabs(["💰 Gastos", "🛠️ Serviços"])

        with tab_gastos:
            if notas.empty:
                st.info("Ainda não há notas cadastradas.")
            else:
                datas_validas = notas["data_nota_dt"].dropna()
                data_min = datas_validas.min().date() if not datas_validas.empty else date.today()
                data_max = datas_validas.max().date() if not datas_validas.empty else date.today()

                st.subheader("Filtros do painel")
                f1, f2, f3, f4 = st.columns(4)
                with f1:
                    inicio = st.date_input("De", value=data_min, key="painel_inicio")
                with f2:
                    fim = st.date_input("Até", value=data_max, key="painel_fim")
                with f3:
                    categorias = sorted([str(x) for x in notas["categoria"].dropna().unique().tolist()])
                    categoria_sel = st.selectbox("Categoria", ["Todas"] + categorias, key="painel_categoria")
                with f4:
                    status_sel = st.selectbox(
                        "Situação",
                        ["Válidas (conferidas + pendentes)", "Somente conferidas", "Somente pendentes", "Todas (inclui rejeitadas)"],
                        key="painel_status"
                    )

                filtradas = notas.copy()
                filtradas = filtradas[
                    (filtradas["data_nota_dt"].dt.date >= inicio) &
                    (filtradas["data_nota_dt"].dt.date <= fim)
                ]
                if categoria_sel != "Todas":
                    filtradas = filtradas[filtradas["categoria"] == categoria_sel]
                if status_sel == "Válidas (conferidas + pendentes)":
                    filtradas = filtradas[filtradas["status"].isin(["Conferida", "Pendente"])]
                elif status_sel == "Somente conferidas":
                    filtradas = filtradas[filtradas["status"] == "Conferida"]
                elif status_sel == "Somente pendentes":
                    filtradas = filtradas[filtradas["status"] == "Pendente"]

                total_gasto = float(filtradas["valor"].sum()) if not filtradas.empty else 0.0
                qtd_notas = len(filtradas)
                pendentes = int((filtradas["status"] == "Pendente").sum()) if not filtradas.empty else 0
                ticket_medio = total_gasto / qtd_notas if qtd_notas else 0.0

                k1, k2, k3, k4 = st.columns(4)
                k1.metric("💰 Total gasto", brl(total_gasto))
                k2.metric("🧾 Notas", qtd_notas)
                k3.metric("⏳ Pendentes", pendentes)
                k4.metric("📌 Gasto médio / nota", brl(ticket_medio))

                if filtradas.empty:
                    st.warning("Nenhum gasto encontrado com esses filtros.")
                else:
                    st.subheader("Visão visual dos gastos")
                    c1, c2 = st.columns(2)
                    with c1:
                        st.markdown("**Gastos por categoria**")
                        por_categoria = (
                            filtradas.groupby("categoria", dropna=False)["valor"]
                            .sum().sort_values(ascending=False)
                        )
                        st.bar_chart(por_categoria)
                    with c2:
                        st.markdown("**Gastos por responsável**")
                        por_resp = (
                            filtradas.groupby("responsavel", dropna=False)["valor"]
                            .sum().sort_values(ascending=False)
                        )
                        st.bar_chart(por_resp)

                    st.markdown("**Evolução dos gastos por mês**")
                    mensal = filtradas.copy()
                    mensal["mês"] = mensal["data_nota_dt"].dt.to_period("M").astype(str)
                    por_mes = mensal.groupby("mês")["valor"].sum().sort_index()
                    st.bar_chart(por_mes)

                    st.subheader("Resumo por categoria")
                    resumo = (
                        filtradas.groupby("categoria", dropna=False)
                        .agg(Notas=("id", "count"), Valor=("valor", "sum"))
                        .reset_index()
                        .sort_values("Valor", ascending=False)
                    )
                    resumo["Valor"] = resumo["Valor"].apply(brl)
                    st.dataframe(resumo, use_container_width=True, hide_index=True)

                    st.subheader("Detalhamento dos gastos")
                    detalhe = filtradas.copy().sort_values("data_nota_dt", ascending=False)
                    detalhe["Data"] = detalhe["data_nota_dt"].dt.strftime("%d/%m/%Y")
                    detalhe["Valor (R$)"] = detalhe["valor"].apply(brl)
                    detalhe["Cliente / Fazenda"] = detalhe.apply(
                        lambda r: " / ".join([x for x in [str(r.get("cliente") or "").strip(), str(r.get("fazenda") or "").strip()] if x]) or "-",
                        axis=1
                    )
                    cols_detalhe = [
                        "Data", "fornecedor", "categoria", "Cliente / Fazenda",
                        "responsavel", "forma_pagamento", "status", "Valor (R$)"
                    ]
                    nomes_colunas = {
                        "fornecedor": "Fornecedor",
                        "categoria": "Categoria",
                        "responsavel": "Responsável",
                        "forma_pagamento": "Pagamento",
                        "status": "Status",
                    }
                    st.dataframe(
                        detalhe[cols_detalhe].rename(columns=nomes_colunas),
                        use_container_width=True,
                        hide_index=True
                    )

                    pdf_bytes = gerar_pdf_gastos(filtradas, inicio, fim)
                    nome_pdf = f"relatorio_gastos_{inicio.strftime('%Y-%m-%d')}_a_{fim.strftime('%Y-%m-%d')}.pdf"
                    st.download_button(
                        "📄 Baixar relatório de gastos em PDF",
                        data=pdf_bytes,
                        file_name=nome_pdf,
                        mime="application/pdf",
                        use_container_width=True,
                    )
                    st.caption("O PDF usa exatamente os filtros selecionados acima. Depois de baixar, você pode abrir e imprimir normalmente.")

        with tab_servicos:
            if servicos.empty:
                st.info("Ainda não há serviços cadastrados.")
            else:
                total_servicos = float(servicos["valor"].sum())
                total_area = float(servicos["area_ha"].sum())
                executados = int((servicos["status"] == "Executado").sum())
                s1, s2, s3, s4 = st.columns(4)
                s1.metric("🛠️ Serviços lançados", len(servicos))
                s2.metric("💵 Valor dos serviços", brl(total_servicos))
                s3.metric("🌱 Área registrada", f"{total_area:,.2f} ha".replace(",", "X").replace(".", ",").replace("X", "."))
                s4.metric("✅ Executados", executados)

                c1, c2 = st.columns(2)
                with c1:
                    st.markdown("**Valor por tipo de serviço**")
                    por_tipo = servicos.groupby("tipo_servico")["valor"].sum().sort_values(ascending=False)
                    st.bar_chart(por_tipo)
                with c2:
                    st.markdown("**Área por tipo de serviço (ha)**")
                    area_tipo = servicos.groupby("tipo_servico")["area_ha"].sum().sort_values(ascending=False)
                    st.bar_chart(area_tipo)

                st.subheader("Últimos serviços")
                sv = servicos.copy().sort_values("data_servico_dt", ascending=False)
                sv["Data"] = sv["data_servico_dt"].dt.strftime("%d/%m/%Y")
                sv["Valor (R$)"] = sv["valor"].apply(brl)
                cols_sv = ["Data", "cliente", "fazenda", "tipo_servico", "area_ha", "responsavel", "status", "Valor (R$)"]
                st.dataframe(
                    sv[cols_sv].rename(columns={
                        "cliente": "Cliente",
                        "fazenda": "Fazenda",
                        "tipo_servico": "Tipo de serviço",
                        "area_ha": "Área (ha)",
                        "responsavel": "Responsável",
                        "status": "Status",
                    }),
                    use_container_width=True,
                    hide_index=True,
                )
    except Exception as e:
        st.error(f"Erro ao montar painel: {e}")

# -----------------------------
# Conferir notas
# -----------------------------
elif menu == "✅ Conferir notas" and is_admin:
    st.title("✅ Conferir notas")
    try:
        r = supabase.table("notas").select("*").order("created_at", desc=True).execute()
        notas = r.data or []
        if not notas:
            st.info("Nenhuma nota cadastrada.")
        else:
            filtro = st.selectbox("Mostrar", ["Pendentes", "Todas", "Conferidas", "Rejeitadas"])
            mapa = {"Pendentes": "Pendente", "Conferidas": "Conferida", "Rejeitadas": "Rejeitada"}
            if filtro != "Todas":
                notas = [n for n in notas if n.get("status") == mapa[filtro]]

            for n in notas:
                with st.expander(f"{n.get('data_nota')} • {n.get('fornecedor')} • {brl(n.get('valor'))} • {n.get('status')}"):
                    c1, c2 = st.columns([2,1])
                    with c1:
                        st.write(f"**Categoria:** {n.get('categoria')}")
                        st.write(f"**Cliente:** {n.get('cliente') or '-'}")
                        st.write(f"**Fazenda:** {n.get('fazenda') or '-'}")
                        st.write(f"**Pagamento:** {n.get('forma_pagamento') or '-'}")
                        st.write(f"**Observação:** {n.get('observacao') or '-'}")
                    with c2:
                        if n.get("arquivo_path"):
                            try:
                                signed = supabase.storage.from_("notas").create_signed_url(n["arquivo_path"], 120)
                                signed_url = signed.get("signedURL") or signed.get("signedUrl")
                                if signed_url:
                                    st.link_button("📎 Abrir comprovante", signed_url, use_container_width=True)
                            except Exception:
                                st.caption("Não foi possível gerar o link do comprovante.")

                    a, b = st.columns(2)
                    if a.button("✅ Marcar como conferida", key=f"ok_{n['id']}", use_container_width=True):
                        supabase.table("notas").update({
                            "status": "Conferida",
                            "conferido_por": st.session_state["user"]["id"],
                            "conferido_em": datetime.utcnow().isoformat()
                        }).eq("id", n["id"]).execute()
                        st.rerun()
                    if b.button("❌ Rejeitar", key=f"no_{n['id']}", use_container_width=True):
                        supabase.table("notas").update({
                            "status": "Rejeitada",
                            "conferido_por": st.session_state["user"]["id"],
                            "conferido_em": datetime.utcnow().isoformat()
                        }).eq("id", n["id"]).execute()
                        st.rerun()
    except Exception as e:
        st.error(f"Erro ao carregar notas: {e}")

# -----------------------------
# Equipe (admin)
# -----------------------------
elif menu == "👥 Equipe" and is_admin:
    st.title("👥 Equipe")
    st.info(
        "Nesta V1, os usuários são criados no painel do Supabase em "
        "**Authentication → Users**. Depois, cadastre o mesmo ID na tabela **profiles** "
        "com o nome e a função (`admin` ou `funcionario`)."
    )
    try:
        r = supabase.table("profiles").select("*").order("nome").execute()
        df = pd.DataFrame(r.data or [])
        if not df.empty:
            st.dataframe(df, use_container_width=True, hide_index=True)
    except Exception as e:
        st.error(f"Erro ao carregar equipe: {e}")
