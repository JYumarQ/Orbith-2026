# Código para renderizar HTML con Jinja2 y convertirlo a PDF con xhtml2pdf
from jinja2 import Environment, FileSystemLoader, select_autoescape
from django.template.loader import get_template
from django.http import HttpResponse
from xhtml2pdf import pisa
from io import BytesIO

class PDFReportGenerator:
    def render_to_pdf(template_src, context_dict={}):
        template = get_template(template_src)
        html = template.render(context_dict)
        result = BytesIO()
        pdf = pisa.pisaDocument(BytesIO(html.encode('ISO-8859-1')), result)
        if not pdf.err:
            return HttpResponse(result.getvalue(), content_type='application/pdf')
        return None