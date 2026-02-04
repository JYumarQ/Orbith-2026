def abreviar_cargo(texto):
    diccionario = {
        "OPERADOR": "OP.",
        "MANTENIMIENTO": "MANT.",
        "FABRICACION": "FAB.", # Sin tilde por si acaso
        "FABRICACIÓN": "FAB.",
        "DEPARTAMENTO": "DPTO.",
        "ESPECIALISTA": "ESP.",
        "GENERAL": "GRAL.",
        "AUXILIAR": "AUX.",
        "TECNICO": "TEC.",
        "TÉCNICO": "TÉC.",
        "SERVICIOS": "SERVS.",
        "ADMINISTRATIVO": "ADMIN.",
    }
    
    palabras = texto.upper().split()
    # Reemplazamos cada palabra si existe en el diccionario
    palabras_nuevas = [diccionario.get(p, p) for p in palabras]
    
    return " ".join(palabras_nuevas)

# USO:
# "OPERADOR B DE FABRICACIÓN Y MANTENIMIENTO" 
# se convierte en:
# "OP. B DE FAB. Y MANT." (Mucho más corto)