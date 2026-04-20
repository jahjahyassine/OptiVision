import os

class Config:
    # Paramètres du serveur WebSocket
    WS_PORT = int(os.getenv("WS_PORT", 8765)) # Port spécifié pour le WebSocket [cite: 48, 187]
    
    # Paramètres de la file d'attente
    MAX_QUEUE_SIZE = int(os.getenv("MAX_QUEUE_SIZE", 5)) # Limite de la file d'attente [cite: 107]
    
    # Paramètres de traitement IA
    INFERENCE_TIMEOUT = float(os.getenv("INFERENCE_TIMEOUT", 0.15)) # Timeout strict de 150ms [cite: 186, 188]
    
    # Paramètres audio
    AUDIO_COOLDOWN = float(os.getenv("AUDIO_COOLDOWN", 3.0)) # 3 secondes entre les alertes [cite: 196, 202]