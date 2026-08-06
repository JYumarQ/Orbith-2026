class ExcelPrinter:
    @staticmethod
    def setup_page(ws, orientation="landscape", header_repeat_row=7):
        """Configuración profesional de impresión en papel."""
        ws.sheet_view.showGridLines = True
        
        if orientation == "landscape":
            ws.page_setup.orientation = ws.ORIENTATION_LANDSCAPE
        else:
            ws.page_setup.orientation = ws.ORIENTATION_PORTRAIT

        ws.page_setup.paperSize = ws.PAPERSIZE_LETTER
        ws.page_setup.fitToWidth = 1
        ws.page_setup.fitToHeight = 0  # Permite extensión de páginas verticales según sea necesario
        
        if header_repeat_row:
            ws.print_title_rows = f'{header_repeat_row}:{header_repeat_row}'
            
        ws.oddFooter.center.text = "Página &P de &N"