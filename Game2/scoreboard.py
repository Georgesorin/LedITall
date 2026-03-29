import pygame
import socket
import json
import colorsys

UDP_IP, UDP_PORT = "127.0.0.1", 4445

pygame.init()

# --- 1. MODIFICARE: SELECTARE MONITOR SECUNDAR ---
num_displays = pygame.display.get_num_displays()
target_display = 1 if num_displays > 1 else 0 # Pune pe monitorul 2 dacă există
screen = pygame.display.set_mode((1280, 720), pygame.RESIZABLE, display=target_display)
# ------------------------------------------------

pygame.display.set_caption("🏆 LIVE SCOREBOARD")

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind((UDP_IP, UDP_PORT))
sock.setblocking(False)

def draw_text_centered(text, font, color, y):
    surf = font.render(text, True, color)
    rect = surf.get_rect(center=(screen.get_width() // 2, y))
    screen.blit(surf, rect)

running, clock = True, pygame.time.Clock()
data = {"scores": [], "time_left": 0, "song_name": "Waiting for DJ...", "num_players": 0}

while running:
    for event in pygame.event.get():
        if event.type == pygame.QUIT: running = False
        if event.type == pygame.KEYDOWN and event.key == pygame.K_f: pygame.display.toggle_fullscreen()

    # --- 2. MODIFICARE: REZOLVARE LAG UDP ---
    # Citim toate pachetele care s-au adunat ca să afișăm doar scorul la zi
    try:
        while True:
            packet, _ = sock.recvfrom(2048)
            data = json.loads(packet.decode())
    except BlockingIOError:
        pass # Am golit coada, totul e in timp real
    except Exception:
        pass
    # ----------------------------------------

    screen.fill((10, 10, 20)) 
    f_title, f_score, f_timer = pygame.font.SysFont("Impact", 45), pygame.font.SysFont("Impact", 65), pygame.font.SysFont("Impact", 120)

    # 1. Titlu (Taiem daca e prea lung)
    txt = data["song_name"][:50] + "..." if len(data["song_name"]) > 50 else data["song_name"]
    draw_text_centered(txt, f_title, (0, 255, 255), 60)

    # 2. Cronometru
    m, s = divmod(data["time_left"], 60)
    draw_text_centered(f"{m:02d}:{s:02d}", f_timer, (255, 255, 255) if data["time_left"] > 10 else (255, 50, 50), 180)

    # 3. Jucători - CENTRARE DINAMICĂ
    n = data["num_players"]
    if n > 0:
        bar_w, bar_h, spacing = 900, 70, 15
        total_h = (n * bar_h) + ((n - 1) * spacing)
        start_y = 280 + ((screen.get_height() - 280) - total_h) // 2

        for i in range(n):
            y_pos = start_y + i * (bar_h + spacing)
            color = [int(c*255) for c in colorsys.hsv_to_rgb(i/max(1.0, float(n)), 0.8, 1)] # Evitam împarțirea fixă la 6.0
            rect = pygame.Rect(0, y_pos, bar_w, bar_h)
            rect.centerx = screen.get_width() // 2
            
            pygame.draw.rect(screen, (30, 30, 45), rect, border_radius=15)
            pygame.draw.rect(screen, color, rect, width=2, border_radius=15)

            name = f_title.render(f"PLAYER {i+1}", True, (255, 255, 255))
            screen.blit(name, name.get_rect(midleft=(rect.left + 30, rect.centery)))
            
            sc = f_score.render(str(data["scores"][i] if i < len(data["scores"]) else 0), True, color)
            screen.blit(sc, sc.get_rect(midright=(rect.right - 30, rect.centery)))

    pygame.display.flip()
    clock.tick(30)
pygame.quit()