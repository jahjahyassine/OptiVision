class PrioritySystem:
    # Définition des niveaux selon le rapport technique [cite: 193-195]
    CRITICAL = 1  # Obstacle < 1m / Collision imminente
    HIGH = 2      # Obstacle 1-2m / Escaliers
    MEDIUM = 3    # Visage connu
    NORMAL = 4    # Texte OCR trouvé
    LOW = 5       # Rien à signaler

    @staticmethod
    def get_priority(event_type: str, metadata: dict) -> int:
        """Détermine la priorité en fonction du type d'objet et de sa distance[cite: 193]."""
        if event_type == "obstacle":
            dist = metadata.get("distance_est")
            if dist == "very_close": return PrioritySystem.CRITICAL
            if dist == "close": return PrioritySystem.HIGH
        
        if event_type == "face":
            return PrioritySystem.MEDIUM
            
        if event_type == "ocr":
            return PrioritySystem.NORMAL
            
        return PrioritySystem.LOW