class DecisionEngine:
    def __init__(self):
        self.last_message = ""

    def decide(self, context):
        """
        Analyse le contexte et retourne un message vocal unique.
        """
        # 1. Extraction des données du dictionnaire
        faces = context.get("faces", [])
        texts = context.get("texts", [])
        objects = context.get("objects", [])

        # 2. Logique de priorité
        # Priorité A : Les visages (Social)
        if faces:
            # On prend le nom du premier visage détecté
            name = faces[0].get('name', 'quelqu\'un')
            if name != self.last_message:
                self.last_message = name
                return f"C'est {name}"

        # Priorité B : Le texte (OCR)
        if texts:
            # On vérifie si c'est une liste de dicts ou du texte brut
            txt_content = ""
            if isinstance(texts, list) and len(texts) > 0:
                txt_content = texts[0].get('text', '') if isinstance(texts[0], dict) else texts[0]
            elif isinstance(texts, str):
                txt_content = texts

            if txt_content and txt_content != self.last_message:
                self.last_message = txt_content
                return f"Je lis : {txt_content}"

        # Si rien de nouveau, on ne dit rien
        return None