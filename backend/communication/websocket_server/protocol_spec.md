# Spécification du Protocole : ESP32-CAM vers Serveur Backend

Ce document définit la structure des messages envoyés par la caméra au serveur via WebSocket.

## 1. Connexion
- **Endpoint :** `ws://<SERVER_IP>:<PORT>/stream`
- **Protocole :** WebSocket (binaire)

## 2. Structure du Paquet de Données (Frame Packet)
Pour éviter que le serveur ne mélange les images ou plante s'il reçoit des données incomplètes, l'ESP32 doit envoyer chaque image en deux parties.

### Étape A : L'En-tête (Header) - 8 Octets
Avant chaque image, la caméra envoie un petit message de 8 octets pour prévenir le serveur de ce qui arrive.

| Octets (Offset) | Taille  | Rôle | Description |
|-----------------|---------|------|-------------|
| `0 à 3`         | 4 bytes | Identifiant | Le mot magique (`0xAV` ou `MAGI`). Permet au serveur de vérifier que c'est bien la bonne caméra. |
| `4 à 7`         | 4 bytes | Longueur | La taille exacte de l'image (en octets) qui va suivre (`fb->len`). |

### Étape B : Le Contenu (Payload)
Immédiatement après l'en-tête, la caméra envoie l'image elle-même.
- **Format :** JPEG compressé
- **Taille :** Correspond à la longueur indiquée dans l'en-tête.

## 3. Logique de Flux (Flow)
1. L'ESP32 se connecte.
2. Boucle : Envoi Header (8 bytes) -> Envoi Image (N bytes) -> Répéter.