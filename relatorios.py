from io import BytesIO
from datetime import datetime
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak


def _brl(v):
    try:
        return f"R$ {float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return "R$ 0,00"


def _fmt_data(v):
    if v is None:
        return "-"
    if hasattr(v, "strftime"):
        return v.strftime("%d/%m/%Y")
    s = str(v)
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
    except Exception:
        return s


def gerar_pdf_gastos(notas_df, inicio, fim, titulo="Relatório de Gastos - Planejar"):
    """Gera um PDF em memória com o resumo e o detalhamento dos gastos filtrados."""
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        rightMargin=12 * mm,
        leftMargin=12 * mm,
        topMargin=12 * mm,
        bottomMargin=14 * mm,
        title=titulo,
        author="Planejar Serviços e Notas",
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "TituloPlanejar",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=18,
        leading=22,
        alignment=TA_CENTER,
        spaceAfter=8,
    )
    subtitle_style = ParagraphStyle(
        "SubtituloPlanejar",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        leading=12,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#444444"),
        spaceAfter=10,
    )
    section_style = ParagraphStyle(
        "SecaoPlanejar",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=11,
        leading=14,
        spaceBefore=8,
        spaceAfter=6,
    )
    small_style = ParagraphStyle(
        "PequenoPlanejar",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=7.5,
        leading=9,
    )
    small_right_style = ParagraphStyle(
        "PequenoDireitaPlanejar",
        parent=small_style,
        alignment=TA_RIGHT,
    )

    story = [
        Paragraph("PLANEJAR - SERVIÇOS E NOTAS", title_style),
        Paragraph(titulo, styles["Heading2"]),
        Paragraph(
            f"Período: {_fmt_data(inicio)} a {_fmt_data(fim)} | Gerado em {datetime.now().strftime('%d/%m/%Y %H:%M')}",
            subtitle_style,
        ),
    ]

    if notas_df is None or notas_df.empty:
        story.append(Paragraph("Nenhum gasto encontrado para os filtros selecionados.", styles["Normal"]))
    else:
        df = notas_df.copy()
        total = float(df["valor"].fillna(0).astype(float).sum()) if "valor" in df.columns else 0.0
        qtd = len(df)
        pendentes = int((df.get("status") == "Pendente").sum()) if "status" in df.columns else 0
        conferidas = int((df.get("status") == "Conferida").sum()) if "status" in df.columns else 0

        resumo_data = [
            ["Total gasto", "Quantidade de notas", "Conferidas", "Pendentes"],
            [_brl(total), str(qtd), str(conferidas), str(pendentes)],
        ]
        resumo = Table(resumo_data, colWidths=[65 * mm, 55 * mm, 45 * mm, 45 * mm])
        resumo.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E9ECEF")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#222222")),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#B0B0B0")),
            ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D0D0D0")),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        story.extend([resumo, Spacer(1, 8)])

        story.append(Paragraph("Resumo por categoria", section_style))
        cat = df.groupby("categoria", dropna=False)["valor"].sum().reset_index().sort_values("valor", ascending=False)
        cat_data = [["Categoria", "Valor", "% do total"]]
        for _, row in cat.iterrows():
            val = float(row["valor"] or 0)
            pct = (val / total * 100) if total else 0
            cat_data.append([
                Paragraph(str(row.get("categoria") or "Sem categoria"), small_style),
                Paragraph(_brl(val), small_right_style),
                Paragraph(f"{pct:.1f}%".replace(".", ","), small_right_style),
            ])
        cat_table = Table(cat_data, colWidths=[105 * mm, 45 * mm, 35 * mm], repeatRows=1)
        cat_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E9ECEF")),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 8),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D0D0D0")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.extend([cat_table, Spacer(1, 10)])

        story.append(Paragraph("Detalhamento dos gastos", section_style))
        header = ["Data", "Fornecedor", "Categoria", "Cliente / Fazenda", "Responsável", "Status", "Valor"]
        detail = [header]
        for _, row in df.sort_values("data_nota").iterrows():
            cliente = str(row.get("cliente") or "-")
            fazenda = str(row.get("fazenda") or "-")
            vinculo = cliente if fazenda == "-" else f"{cliente} / {fazenda}"
            detail.append([
                Paragraph(_fmt_data(row.get("data_nota")), small_style),
                Paragraph(str(row.get("fornecedor") or "-"), small_style),
                Paragraph(str(row.get("categoria") or "-"), small_style),
                Paragraph(vinculo, small_style),
                Paragraph(str(row.get("responsavel") or "-"), small_style),
                Paragraph(str(row.get("status") or "-"), small_style),
                Paragraph(_brl(row.get("valor") or 0), small_right_style),
            ])

        detail_table = Table(
            detail,
            colWidths=[24 * mm, 47 * mm, 36 * mm, 61 * mm, 34 * mm, 28 * mm, 31 * mm],
            repeatRows=1,
        )
        detail_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E9ECEF")),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 7.5),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D0D0D0")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ALIGN", (-1, 1), (-1, -1), "RIGHT"),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        story.append(detail_table)

    def _footer(canvas, doc_obj):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.HexColor("#666666"))
        canvas.drawString(12 * mm, 7 * mm, "Planejar Serviços e Notas")
        canvas.drawRightString(landscape(A4)[0] - 12 * mm, 7 * mm, f"Página {doc_obj.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    buffer.seek(0)
    return buffer.getvalue()
