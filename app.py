
import streamlit as st
from supabase import create_client
from datetime import date, datetime
from decimal import Decimal
import uuid
import re
from io import BytesIO
import pandas as pd
from PIL import Image, ImageOps, ImageEnhance, ImageFilter
import pytesseract
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

def get_supabase_admin():
    """Cliente administrativo usado somente para criar usuários.
    A SERVICE_ROLE_KEY deve ficar apenas nos Secrets do Streamlit.
    """
    key = st.secrets.get("SUPABASE_SERVICE_ROLE_KEY")
    if not key:
        return None
    return create_client(st.secrets["SUPABASE_URL"], key)

def brl(v):
    try:
        return f"R$ {float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except:
        return "R$ 0,00"


def _valor_brasileiro_para_float(txt):
    if not txt:
        return 0.0
    t = str(txt).strip().replace("R$", "").replace(" ", "")
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    else:
        # Se houver um único ponto e 2 casas depois, pode ser decimal.
        partes = t.split(".")
        if len(partes) > 2:
            t = "".join(partes)
    try:
        return float(t)
    except Exception:
        return 0.0


def _inferir_categoria_ocr(texto):
    t = (texto or "").lower()
    regras = [
        ("Combustível", ["combust", "gasolina", "diesel", "etanol", "posto ", "litros", "litro"]),
        ("Alimentação", ["restaurante", "lanchonete", "refeicao", "refeição", "alimento", "mercado", "supermercado"]),
        ("Hospedagem", ["hotel", "pousada", "hospedagem", "diaria", "diária"]),
        ("Pedágio", ["pedagio", "pedágio", "concessionaria", "concessionária"]),
        ("Manutenção", ["manutencao", "manutenção", "oficina", "mecanica", "mecânica", "reparo"]),
        ("Peças", ["pecas", "peças", "auto pecas", "autopeças", "rolamento", "filtro", "correia"]),
        ("Material de escritório", ["papelaria", "escritorio", "escritório", "toner", "cartucho"]),
        ("Carbono", ["carbono", "carbon credit"]),
        ("Campo / Coleta", ["coleta", "amostragem", "campo"]),
    ]
    for categoria, palavras in regras:
        if any(p in t for p in palavras):
            return categoria
    return "Outros"


def _inferir_pagamento_ocr(texto):
    t = (texto or "").lower()
    if "pix" in t:
        return "Pix"
    if any(x in t for x in ["cartao", "cartão", "credito", "crédito", "debito", "débito"]):
        return "Cartão"
    if "dinheiro" in t:
        return "Dinheiro"
    if "boleto" in t:
        return "Boleto"
    if any(x in t for x in ["transferencia", "transferência", "ted", "doc banc"]):
        return "Transferência"
    return "Outro"


def extrair_dados_nota_ocr(texto):
    """Extrai sugestões do OCR. Tudo continua editável antes do envio."""
    texto = texto or ""
    linhas = [re.sub(r"\s+", " ", x).strip() for x in texto.splitlines() if x.strip()]

    # CNPJ
    m_cnpj = re.search(r"\b\d{2}[. ]?\d{3}[. ]?\d{3}[/ ]?\d{4}-?\d{2}\b", texto)
    cnpj = m_cnpj.group(0) if m_cnpj else ""

    # Data: primeira data plausível encontrada.
    data_encontrada = None
    for padrao in [r"\b(\d{2})[/-](\d{2})[/-](\d{4})\b", r"\b(\d{2})[/-](\d{2})[/-](\d{2})\b"]:
        for m in re.finditer(padrao, texto):
            try:
                d, mes, ano = [int(x) for x in m.groups()]
                if ano < 100:
                    ano += 2000
                candidata = date(ano, mes, d)
                if 2000 <= candidata.year <= date.today().year + 2:
                    data_encontrada = candidata
                    break
            except Exception:
                pass
        if data_encontrada:
            break

    # Número da nota: tenta linhas marcadas como NF/NFC-e/NFe/Nota.
    numero_nota = ""
    padroes_numero = [
        r"(?:NF-?E|NFC-?E|NFE|NOTA\s+FISCAL|NOTA|N[º°O]?)\s*[:#.-]?\s*(\d{3,12})",
        r"(?:NUMERO|NÚMERO)\s*[:#.-]?\s*(\d{3,12})",
    ]
    for padrao in padroes_numero:
        m = re.search(padrao, texto, flags=re.I)
        if m:
            numero_nota = m.group(1)
            break

    # Valor total: prioriza linhas contendo TOTAL / A PAGAR / VALOR.
    valores_prioritarios = []
    valores_gerais = []
    moeda = re.compile(r"(?:R\$\s*)?(\d{1,3}(?:\.\d{3})*,\d{2}|\d+[.,]\d{2})")
    for linha in linhas:
        encontrados = [m.group(1) for m in moeda.finditer(linha)]
        nums = [_valor_brasileiro_para_float(x) for x in encontrados]
        nums = [x for x in nums if x > 0]
        valores_gerais.extend(nums)
        if any(chave in linha.lower() for chave in ["total", "a pagar", "valor pago", "valor da nota", "vl total"]):
            valores_prioritarios.extend(nums)
    valor = max(valores_prioritarios) if valores_prioritarios else (max(valores_gerais) if valores_gerais else 0.0)

    # Fornecedor: procura no início uma linha com letras e que não pareça cabeçalho fiscal.
    fornecedor = ""
    ignorar = ["danfe", "documento auxiliar", "nota fiscal", "nf-e", "nfce", "nfc-e", "cnpj", "cpf", "emissao", "emissão", "cupom fiscal"]
    for linha in linhas[:12]:
        low = linha.lower()
        if len(linha) < 4 or len(linha) > 90:
            continue
        if any(x in low for x in ignorar):
            continue
        if re.search(r"[A-Za-zÀ-ÿ]{3,}", linha) and not re.fullmatch(r"[\d .,/:-]+", linha):
            fornecedor = linha
            break

    return {
        "fornecedor": fornecedor,
        "data": data_encontrada or date.today(),
        "valor": float(valor or 0.0),
        "cnpj": cnpj,
        "numero_nota": numero_nota,
        "categoria": _inferir_categoria_ocr(texto),
        "forma_pagamento": _inferir_pagamento_ocr(texto),
        "texto": texto.strip(),
    }


def ler_foto_nota_ocr(conteudo):
    """OCR local/gratuito via Tesseract. Retorna texto + sugestões de campos."""
    imagem = Image.open(BytesIO(conteudo))
    # Corrige rotação do celular antes do OCR.
    imagem = ImageOps.exif_transpose(imagem).convert("RGB")
    cinza = ImageOps.grayscale(imagem)
    cinza = ImageEnhance.Contrast(cinza).enhance(1.8)
    cinza = cinza.filter(ImageFilter.SHARPEN)
    try:
        texto = pytesseract.image_to_string(cinza, lang="por", config="--psm 6")
    except Exception:
        # Fallback caso o pacote de idioma português não esteja disponível.
        texto = pytesseract.image_to_string(cinza, config="--psm 6")
    return extrair_dados_nota_ocr(texto)


def registrar_historico_nota(nota_id, acao, detalhes=None):
    """Registra alterações importantes da nota sem interromper o app se o log falhar."""
    try:
        supabase.table("notas_historico").insert({
            "nota_id": nota_id,
            "usuario_id": st.session_state["user"]["id"],
            "acao": acao,
            "detalhes": detalhes
        }).execute()
    except Exception:
        pass

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

role = profile.get("role", "funcionario")
is_admin = role == "admin"
is_gerente = role == "gerente"
is_gestao = role in ("admin", "gerente")
nome_usuario = profile.get("nome") or st.session_state["user"]["email"]

# -----------------------------
# Sidebar
# -----------------------------
st.sidebar.title("🌱 Planejar")
st.sidebar.write(f"**{nome_usuario}**")
st.sidebar.caption({"admin": "Administrador", "gerente": "Gerente"}.get(role, "Equipe"))

menu_items = ["🏠 Início", "🛠️ Adicionar serviço", "🧾 Adicionar nota", "📋 Meus lançamentos"]
if is_gestao:
    menu_items += ["📊 Painel administrativo", "🛠️ Conferir serviços", "✅ Conferir notas", "👥 Equipe"]

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
    st.caption("Tire a foto pelo celular ou envie uma foto/PDF. Em fotos, o app pode tentar preencher os dados automaticamente.")

    modo_anexo = st.radio(
        "Como deseja anexar?",
        ["📷 Tirar foto agora", "📁 Enviar foto/PDF"],
        horizontal=True,
        key="modo_anexo_nota",
    )

    if modo_anexo == "📷 Tirar foto agora":
        arquivo = st.camera_input("Fotografe a nota", key="camera_nota")
    else:
        arquivo = st.file_uploader(
            "Foto/PDF da nota *",
            type=["jpg", "jpeg", "png", "pdf"],
            key="upload_nota",
        )

    eh_imagem = bool(arquivo) and (
        (getattr(arquivo, "type", "") or "").startswith("image/")
        or str(getattr(arquivo, "name", "")).lower().endswith((".jpg", ".jpeg", ".png"))
    )

    if arquivo and eh_imagem:
        if st.button("✨ Ler dados da foto automaticamente", use_container_width=True):
            try:
                with st.spinner("Lendo a nota..."):
                    st.session_state["nota_ocr_resultado"] = ler_foto_nota_ocr(arquivo.getvalue())
                st.success("Leitura concluída. Confira os dados antes de enviar.")
            except Exception as e:
                st.session_state.pop("nota_ocr_resultado", None)
                st.warning(f"Não consegui ler essa foto automaticamente. Você ainda pode preencher os campos manualmente. Detalhe: {e}")
    elif arquivo and not eh_imagem:
        st.info("A leitura automática está disponível para fotos. O PDF continua podendo ser anexado normalmente.")

    ocr = st.session_state.get("nota_ocr_resultado") or {}

    if ocr:
        st.subheader("🔎 Dados encontrados na foto")
        o1, o2, o3, o4 = st.columns(4)
        o1.metric("Fornecedor", ocr.get("fornecedor") or "Não identificado")
        o2.metric("Valor", brl(ocr.get("valor") or 0))
        o3.metric("CNPJ", ocr.get("cnpj") or "Não identificado")
        o4.metric("Nº da nota", ocr.get("numero_nota") or "Não identificado")
        st.caption("Esses dados são apenas sugestões da leitura da imagem. Confira e corrija o que for necessário.")
        if ocr.get("texto"):
            with st.expander("📝 Ver texto reconhecido na foto"):
                st.text(ocr["texto"][:6000])

    categorias = [
        "Combustível", "Manutenção", "Peças", "Alimentação", "Hospedagem",
        "Pedágio", "Material de escritório", "Campo / Coleta", "Carbono", "Outros"
    ]
    formas = ["Pix", "Cartão", "Dinheiro", "Boleto", "Transferência", "Outro"]
    cat_ocr = ocr.get("categoria") if ocr.get("categoria") in categorias else "Outros"
    forma_ocr = ocr.get("forma_pagamento") if ocr.get("forma_pagamento") in formas else "Outro"

    with st.form("nota_form", clear_on_submit=True):
        c1, c2 = st.columns(2)
        with c1:
            data_nota = st.date_input("Data da nota", value=ocr.get("data") or date.today())
            fornecedor = st.text_input("Fornecedor *", value=ocr.get("fornecedor") or "")
            valor_nota = st.number_input(
                "Valor (R$) *",
                min_value=0.0,
                step=1.0,
                value=float(ocr.get("valor") or 0.0),
            )
            categoria = st.selectbox("Categoria", categorias, index=categorias.index(cat_ocr))
        with c2:
            cliente_nota = st.text_input("Cliente / Produtor relacionado")
            fazenda_nota = st.text_input("Fazenda relacionada")
            forma_pagamento = st.selectbox("Forma de pagamento", formas, index=formas.index(forma_ocr))
            observacao_nota = st.text_area("Observação")

        enviar = st.form_submit_button("📤 Enviar nota", use_container_width=True)

    if enviar:
        if not arquivo:
            st.error("Anexe ou tire uma foto da nota.")
        elif not fornecedor.strip():
            st.error("Informe o fornecedor.")
        elif valor_nota <= 0:
            st.error("Informe um valor maior que zero.")
        else:
            try:
                nome_original = getattr(arquivo, "name", "") or f"foto_nota_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
                if "." in nome_original:
                    ext = nome_original.rsplit(".", 1)[-1].lower()
                else:
                    ext = "jpg" if eh_imagem else "bin"
                uid = st.session_state["user"]["id"]
                nome_arquivo = f"{uid}/{datetime.now().strftime('%Y/%m')}/{uuid.uuid4().hex}.{ext}"
                conteudo = arquivo.getvalue()
                supabase.storage.from_("notas").upload(
                    nome_arquivo,
                    conteudo,
                    {"content-type": getattr(arquivo, "type", None) or "application/octet-stream", "upsert": "false"}
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
                    "arquivo_nome_original": nome_original,
                    "status": "Pendente"
                }
                supabase.table("notas").insert(payload).execute()
                st.session_state.pop("nota_ocr_resultado", None)
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
            notas_usuario = r.data or []
            if not notas_usuario:
                st.info("Nenhuma nota lançada ainda.")
            else:
                st.caption("Notas **Pendentes** podem ser editadas. Depois de conferidas, ficam bloqueadas até o administrador liberar novamente.")

                # Carrega o histórico em uma única consulta. Se a tabela ainda não existir, o app continua funcionando.
                historico_por_nota = {}
                try:
                    rh = supabase.table("notas_historico").select("*").order("created_at", desc=True).execute()
                    for h in (rh.data or []):
                        historico_por_nota.setdefault(h.get("nota_id"), []).append(h)
                except Exception:
                    historico_por_nota = {}

                categorias_nota = [
                    "Combustível", "Manutenção", "Peças", "Alimentação", "Hospedagem",
                    "Pedágio", "Material de escritório", "Campo / Coleta", "Carbono", "Outros"
                ]
                formas_pagamento = ["Pix", "Cartão", "Dinheiro", "Boleto", "Transferência", "Outro"]

                for n in notas_usuario:
                    status_nota = n.get("status") or "Pendente"
                    icone_status = "🟡" if status_nota == "Pendente" else ("✅" if status_nota == "Conferida" else "❌")
                    titulo = f"{icone_status} {n.get('data_nota')} • {n.get('fornecedor')} • {brl(n.get('valor'))} • {status_nota}"

                    with st.expander(titulo):
                        c1, c2 = st.columns(2)
                        with c1:
                            st.write(f"**Categoria:** {n.get('categoria') or '-'}")
                            st.write(f"**Cliente:** {n.get('cliente') or '-'}")
                            st.write(f"**Fazenda:** {n.get('fazenda') or '-'}")
                        with c2:
                            st.write(f"**Pagamento:** {n.get('forma_pagamento') or '-'}")
                            st.write(f"**Observação:** {n.get('observacao') or '-'}")
                            if n.get("arquivo_path"):
                                try:
                                    signed = supabase.storage.from_("notas").create_signed_url(n["arquivo_path"], 120)
                                    signed_url = signed.get("signedURL") or signed.get("signedUrl")
                                    if signed_url:
                                        st.link_button("📎 Abrir comprovante", signed_url, use_container_width=True)
                                except Exception:
                                    st.caption("Não foi possível gerar o link do comprovante.")

                        if status_nota == "Pendente":
                            st.divider()
                            st.subheader("✏️ Editar nota")

                            try:
                                data_atual = datetime.strptime(str(n.get("data_nota")), "%Y-%m-%d").date()
                            except Exception:
                                data_atual = date.today()

                            categoria_atual = n.get("categoria") or "Outros"
                            if categoria_atual not in categorias_nota:
                                categorias_nota_edicao = categorias_nota + [categoria_atual]
                            else:
                                categorias_nota_edicao = categorias_nota

                            pagamento_atual = n.get("forma_pagamento") or "Outro"
                            if pagamento_atual not in formas_pagamento:
                                formas_pagamento_edicao = formas_pagamento + [pagamento_atual]
                            else:
                                formas_pagamento_edicao = formas_pagamento

                            with st.form(f"editar_nota_{n['id']}"):
                                e1, e2 = st.columns(2)
                                with e1:
                                    nova_data = st.date_input("Data da nota", value=data_atual, key=f"data_ed_{n['id']}")
                                    novo_fornecedor = st.text_input("Fornecedor *", value=n.get("fornecedor") or "", key=f"forn_ed_{n['id']}")
                                    novo_valor = st.number_input("Valor (R$) *", min_value=0.0, step=1.0, value=float(n.get("valor") or 0), key=f"valor_ed_{n['id']}")
                                    nova_categoria = st.selectbox(
                                        "Categoria", categorias_nota_edicao,
                                        index=categorias_nota_edicao.index(categoria_atual),
                                        key=f"cat_ed_{n['id']}"
                                    )
                                with e2:
                                    novo_cliente = st.text_input("Cliente / Produtor relacionado", value=n.get("cliente") or "", key=f"cli_ed_{n['id']}")
                                    nova_fazenda = st.text_input("Fazenda relacionada", value=n.get("fazenda") or "", key=f"faz_ed_{n['id']}")
                                    nova_forma = st.selectbox(
                                        "Forma de pagamento", formas_pagamento_edicao,
                                        index=formas_pagamento_edicao.index(pagamento_atual),
                                        key=f"pag_ed_{n['id']}"
                                    )
                                    nova_observacao = st.text_area("Observação", value=n.get("observacao") or "", key=f"obs_ed_{n['id']}")

                                salvar_edicao = st.form_submit_button("💾 Salvar alterações", use_container_width=True)

                            if salvar_edicao:
                                if not novo_fornecedor.strip():
                                    st.error("Informe o fornecedor.")
                                elif novo_valor <= 0:
                                    st.error("Informe um valor maior que zero.")
                                else:
                                    alteracoes = []
                                    campos_comparacao = [
                                        ("data", str(n.get("data_nota") or ""), str(nova_data)),
                                        ("fornecedor", str(n.get("fornecedor") or ""), novo_fornecedor.strip()),
                                        ("valor", float(n.get("valor") or 0), float(novo_valor)),
                                        ("categoria", str(n.get("categoria") or ""), nova_categoria),
                                        ("cliente", str(n.get("cliente") or ""), novo_cliente.strip()),
                                        ("fazenda", str(n.get("fazenda") or ""), nova_fazenda.strip()),
                                        ("pagamento", str(n.get("forma_pagamento") or ""), nova_forma),
                                        ("observação", str(n.get("observacao") or ""), nova_observacao.strip()),
                                    ]
                                    for campo, antes, depois in campos_comparacao:
                                        if antes != depois:
                                            alteracoes.append(campo)

                                    payload_edicao = {
                                        "data_nota": str(nova_data),
                                        "fornecedor": novo_fornecedor.strip(),
                                        "valor": float(novo_valor),
                                        "categoria": nova_categoria,
                                        "cliente": novo_cliente.strip() or None,
                                        "fazenda": nova_fazenda.strip() or None,
                                        "forma_pagamento": nova_forma,
                                        "observacao": nova_observacao.strip() or None,
                                        # Mantém a nota pendente; usuário comum não consegue liberar nota já conferida.
                                        "status": "Pendente"
                                    }
                                    supabase.table("notas").update(payload_edicao).eq("id", n["id"]).eq("usuario_id", uid).eq("status", "Pendente").execute()
                                    detalhes = "Campos alterados: " + ", ".join(alteracoes) if alteracoes else "Salvo sem alteração de campos."
                                    registrar_historico_nota(n["id"], "Nota editada", detalhes)
                                    st.success("Alterações salvas. A nota continua pendente de conferência.")
                                    st.rerun()
                        else:
                            st.info("🔒 Esta nota está bloqueada. Somente o administrador pode liberar novamente para edição.")

                        historico = historico_por_nota.get(n.get("id"), [])
                        if historico:
                            st.divider()
                            with st.expander("🕘 Histórico de alterações"):
                                for h in historico[:20]:
                                    quando = str(h.get("created_at") or "").replace("T", " ")[:19]
                                    st.write(f"**{quando}** — {h.get('acao')}")
                                    if h.get("detalhes"):
                                        st.caption(h.get("detalhes"))
        except Exception as e:
            st.error(f"Erro ao carregar notas: {e}")

# -----------------------------
# Painel admin
# -----------------------------
elif menu == "📊 Painel administrativo" and is_gestao:
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
# Conferir serviços
# -----------------------------
elif menu == "🛠️ Conferir serviços" and is_gestao:
    st.title("🛠️ Conferir serviços")
    st.caption("Confira, edite ou exclua serviços lançados pela equipe.")
    try:
        rs = supabase.table("servicos").select("*").order("created_at", desc=True).execute()
        rp = supabase.table("profiles").select("id,nome").execute()
        nomes = {x["id"]: x.get("nome", "") for x in (rp.data or [])}
        servicos_lista = rs.data or []

        if not servicos_lista:
            st.info("Nenhum serviço cadastrado.")
        else:
            busca = st.text_input("🔎 Buscar por cliente, fazenda ou serviço")
            if busca.strip():
                termo = busca.strip().lower()
                servicos_lista = [x for x in servicos_lista if termo in " ".join([
                    str(x.get("cliente") or ""), str(x.get("fazenda") or ""),
                    str(x.get("tipo_servico") or ""), nomes.get(x.get("usuario_id"), "")
                ]).lower()]

            for sv in servicos_lista:
                resp = nomes.get(sv.get("usuario_id"), "Não identificado")
                titulo = f"{sv.get('data_servico')} • {sv.get('cliente')} • {sv.get('tipo_servico')} • {brl(sv.get('valor'))}"
                with st.expander(titulo):
                    st.caption(f"Responsável: {resp}")
                    with st.form(f"edit_servico_{sv['id']}"):
                        c1, c2 = st.columns(2)
                        with c1:
                            d = st.date_input("Data", value=pd.to_datetime(sv.get("data_servico")).date(), key=f"d_{sv['id']}")
                            cli = st.text_input("Cliente / Produtor", value=sv.get("cliente") or "", key=f"cli_{sv['id']}")
                            faz = st.text_input("Fazenda", value=sv.get("fazenda") or "", key=f"faz_{sv['id']}")
                            tipos = ["Coleta de solo", "Agricultura de precisão", "Carbono / Sensoriamento de carbono", "Mapeamento", "Regulagem de máquina", "Visita técnica", "Laudo", "Outro"]
                            atual_tipo = sv.get("tipo_servico") or "Outro"
                            if atual_tipo not in tipos:
                                tipos.append(atual_tipo)
                            tp = st.selectbox("Tipo de serviço", tipos, index=tipos.index(atual_tipo), key=f"tp_{sv['id']}")
                        with c2:
                            ar = st.number_input("Área (ha)", min_value=0.0, value=float(sv.get("area_ha") or 0), step=0.01, key=f"ar_{sv['id']}")
                            val = st.number_input("Valor (R$)", min_value=0.0, value=float(sv.get("valor") or 0), step=10.0, key=f"val_{sv['id']}")
                            sts = ["Executado", "Em andamento", "Agendado"]
                            atual_st = sv.get("status") or "Executado"
                            if atual_st not in sts:
                                sts.append(atual_st)
                            stat = st.selectbox("Status", sts, index=sts.index(atual_st), key=f"sts_{sv['id']}")
                            obs = st.text_area("Observação", value=sv.get("observacao") or "", key=f"obs_{sv['id']}")
                        salvar_edicao = st.form_submit_button("💾 Salvar alterações", use_container_width=True)
                    if salvar_edicao:
                        if not cli.strip():
                            st.error("Informe o cliente/produtor.")
                        else:
                            supabase.table("servicos").update({
                                "data_servico": str(d), "cliente": cli.strip(), "fazenda": faz.strip() or None,
                                "tipo_servico": tp, "area_ha": float(ar), "valor": float(val),
                                "status": stat, "observacao": obs.strip() or None
                            }).eq("id", sv["id"]).execute()
                            st.success("Serviço atualizado.")
                            st.rerun()

                    confirmar = st.checkbox("Confirmar exclusão deste serviço", key=f"conf_del_sv_{sv['id']}")
                    if st.button("🗑️ Excluir serviço", key=f"del_sv_{sv['id']}", disabled=not confirmar, use_container_width=True):
                        supabase.table("servicos").delete().eq("id", sv["id"]).execute()
                        st.success("Serviço excluído.")
                        st.rerun()
    except Exception as e:
        st.error(f"Erro ao carregar serviços: {e}")

# -----------------------------
# Conferir notas
# -----------------------------
elif menu == "✅ Conferir notas" and is_gestao:
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

                    status_atual = n.get("status") or "Pendente"
                    if status_atual == "Pendente":
                        a, b = st.columns(2)
                        if a.button("✅ Marcar como conferida", key=f"ok_{n['id']}", use_container_width=True):
                            supabase.table("notas").update({
                                "status": "Conferida",
                                "conferido_por": st.session_state["user"]["id"],
                                "conferido_em": datetime.utcnow().isoformat()
                            }).eq("id", n["id"]).execute()
                            registrar_historico_nota(n["id"], "Nota conferida", f"Conferida por {nome_usuario}.")
                            st.rerun()
                        if b.button("❌ Rejeitar", key=f"no_{n['id']}", use_container_width=True):
                            supabase.table("notas").update({
                                "status": "Rejeitada",
                                "conferido_por": st.session_state["user"]["id"],
                                "conferido_em": datetime.utcnow().isoformat()
                            }).eq("id", n["id"]).execute()
                            registrar_historico_nota(n["id"], "Nota rejeitada", f"Rejeitada por {nome_usuario}.")
                            st.rerun()
                    else:
                        st.info("🔒 Nota bloqueada para edição.")
                        if is_admin:
                            if st.button("🔓 Liberar para edição", key=f"unlock_{n['id']}", use_container_width=True):
                                supabase.table("notas").update({
                                    "status": "Pendente",
                                    "conferido_por": None,
                                    "conferido_em": None
                                }).eq("id", n["id"]).execute()
                                registrar_historico_nota(
                                    n["id"],
                                    "Edição liberada",
                                    f"Liberada pelo administrador {nome_usuario}. A nota voltou para Pendente."
                                )
                                st.success("Edição liberada. A nota voltou para Pendente.")
                                st.rerun()
                        else:
                            st.caption("Apenas o administrador pode liberar esta nota novamente para edição.")

                    st.divider()
                    confirmar_nota = st.checkbox("Confirmar exclusão desta nota", key=f"conf_del_n_{n['id']}")
                    if st.button("🗑️ Excluir nota", key=f"del_n_{n['id']}", disabled=not confirmar_nota, use_container_width=True):
                        if n.get("arquivo_path"):
                            try:
                                supabase.storage.from_("notas").remove([n["arquivo_path"]])
                            except Exception:
                                pass
                        supabase.table("notas").delete().eq("id", n["id"]).execute()
                        st.success("Nota excluída.")
                        st.rerun()
    except Exception as e:
        st.error(f"Erro ao carregar notas: {e}")

# -----------------------------
# Equipe (gestão)
# -----------------------------
elif menu == "👥 Equipe" and is_gestao:
    st.title("👥 Equipe")

    if is_admin:
        st.subheader("➕ Cadastrar usuário")
        st.caption("Crie o acesso do funcionário ou gerente diretamente pelo aplicativo.")
        admin_client = get_supabase_admin()
        if admin_client is None:
            st.warning("Para liberar o cadastro direto, adicione SUPABASE_SERVICE_ROLE_KEY nos Secrets do Streamlit.")
        else:
            with st.form("novo_usuario", clear_on_submit=True):
                nome_novo = st.text_input("Nome *")
                email_novo = st.text_input("E-mail *")
                senha_nova = st.text_input("Senha inicial *", type="password", help="Use pelo menos 6 caracteres.")
                role_nova = st.selectbox("Função", ["funcionario", "gerente", "admin"], format_func=lambda x: {"funcionario":"Funcionário", "gerente":"Gerente", "admin":"Administrador"}[x])
                criar = st.form_submit_button("👤 Criar usuário", use_container_width=True)

            if criar:
                if not nome_novo.strip() or not email_novo.strip() or len(senha_nova) < 6:
                    st.error("Preencha nome, e-mail e uma senha com pelo menos 6 caracteres.")
                else:
                    novo_id = None
                    try:
                        resp = admin_client.auth.admin.create_user({
                            "email": email_novo.strip(),
                            "password": senha_nova,
                            "email_confirm": True
                        })
                        novo_id = resp.user.id
                        admin_client.table("profiles").insert({
                            "id": novo_id, "nome": nome_novo.strip(), "role": role_nova, "ativo": True
                        }).execute()
                        st.success(f"Usuário {nome_novo.strip()} criado com sucesso.")
                        st.rerun()
                    except Exception as e:
                        if novo_id:
                            try:
                                admin_client.auth.admin.delete_user(novo_id)
                            except Exception:
                                pass
                        st.error(f"Não foi possível criar o usuário: {e}")

    st.subheader("Usuários cadastrados")
    try:
        r = supabase.table("profiles").select("*").order("nome").execute()
        perfis_lista = r.data or []
        if not perfis_lista:
            st.info("Nenhum usuário cadastrado.")
        else:
            df = pd.DataFrame(perfis_lista)
            cols = [c for c in ["nome", "role", "ativo", "created_at"] if c in df.columns]
            st.dataframe(df[cols], use_container_width=True, hide_index=True)

            if is_admin:
                st.subheader("Alterar função / situação")
                opcoes = {f"{x.get('nome')} — {x.get('role')}": x for x in perfis_lista}
                escolhido = st.selectbox("Usuário", list(opcoes.keys()))
                alvo = opcoes[escolhido]
                roles = ["funcionario", "gerente", "admin"]
                nova_role = st.selectbox("Nova função", roles, index=roles.index(alvo.get("role", "funcionario")), format_func=lambda x: {"funcionario":"Funcionário", "gerente":"Gerente", "admin":"Administrador"}[x])
                novo_ativo = st.checkbox("Usuário ativo", value=bool(alvo.get("ativo", True)))
                if st.button("💾 Salvar usuário", use_container_width=True):
                    if alvo["id"] == st.session_state["user"]["id"] and (nova_role != "admin" or not novo_ativo):
                        st.error("Você não pode retirar seu próprio acesso de administrador por esta tela.")
                    else:
                        supabase.table("profiles").update({"role": nova_role, "ativo": novo_ativo}).eq("id", alvo["id"]).execute()
                        st.success("Usuário atualizado.")
                        st.rerun()
    except Exception as e:
        st.error(f"Erro ao carregar equipe: {e}")
