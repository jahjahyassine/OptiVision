# import os
# import asyncio
# import pygame
# from TTS.api import TTS

# class CoquiTTS:
#     def __init__(self, model_name="tts_models/fr/css10/vits", use_gpu=False):
#         """
#         Initialise la véritable IA vocale de Coqui.
#         Le modèle par défaut ici est une voix française (vits).
#         """
#         print("Chargement du modèle d'IA vocale Coqui TTS (cela peut prendre du temps)...")
        
#         # 1. Chargement du vrai modèle IA
#         self.tts = TTS(model_name=model_name, progress_bar=False, gpu=use_gpu)
        
#         # 2. Initialisation du mixeur audio (pour lire et couper le son)
#         pygame.mixer.init()
#         self._is_playing = False
#         print("Coqui TTS est prêt !")

#     async def speak_async(self, message: str):
#         """Transforme le texte en voix et le lit avec interruption possible."""
#         print(f"🔊 [Coqui TTS] : '{message}'")
        
#         audio_file = "temp_alert.wav"
#         self._is_playing = True
        
#         try:
#             # ÉTAPE 1 : Génération du fichier audio par l'IA
#             # On utilise asyncio.to_thread car la génération IA est lourde.
#             # Si on ne fait pas ça, le serveur va bloquer et la caméra va freezer !
#             await asyncio.to_thread(self.tts.tts_to_file, text=message, file_path=audio_file)
            
#             # ÉTAPE 2 : Si une urgence a annulé la lecture pendant la génération, on s'arrête
#             if not self._is_playing:
#                 return

#             # ÉTAPE 3 : Lecture du fichier audio
#             pygame.mixer.music.load(audio_file)
#             pygame.mixer.music.play()
            
#             # ÉTAPE 4 : On attend que l'audio se termine... ou qu'il soit interrompu
#             while pygame.mixer.music.get_busy() and self._is_playing:
#                 await asyncio.sleep(0.05) # Vérifie toutes les 50ms
                
#         except Exception as e:
#             print(f"Erreur TTS : {e}")
            
#         finally:
#             # ÉTAPE 5 : Nettoyage (on libère le fichier et on le supprime)
#             pygame.mixer.music.unload()
#             if os.path.exists(audio_file):
#                 try:
#                     os.remove(audio_file)
#                 except OSError:
#                     pass # Le fichier est peut-être encore bloqué par le système

#     def interrupt(self):
#         """Actionne le vrai bouton d'arrêt d'urgence de la voix."""
#         self._is_playing = False
#         if pygame.mixer.music.get_busy():
#             print("🛑 [Audio coupé instantanément pour une urgence !]")
#             pygame.mixer.music.stop() # Coupe le son de pygame immédiatement