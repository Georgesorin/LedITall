import pygame
import socket
import json
import colorsys

# ==============================================================================
# --- THE RADIO CHANNEL ---
# This is the secret channel where we listen for the DJ's walkie-talkie.
# "127.0.0.1" means "listen to the computer I am currently running on".
# ==============================================================================
UDP_IP, UDP_PORT = "127.0.0.1", 4445

# Wake up the painting tools!
pygame.init()

# ==============================================================================
# --- WHERE TO PUT THE TV? (MONITOR SETUP) ---
# We ask the computer: "Hey, do you have a second screen plugged in (like a projector)?"
# If YES, we put the scoreboard on screen 2 (target_display = 1).
# If NO, we keep it on the main screen (target_display = 0).
# ==============================================================================
num_displays = pygame.display.get_num_displays()
target_display = 1 if num_displays > 1 else 0 
screen = pygame.display.set_mode((1280, 720), pygame.RESIZABLE, display=target_display)

pygame.display.set_caption("🏆 LIVE SCOREBOARD")

# ==============================================================================
# --- SETTING UP THE EAR (SOCKET) ---
# We create a listening walkie-talkie and tell it to never freeze the game 
# while waiting for a message (that's what "setblocking(False)" means).
# ==============================================================================
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind((UDP_IP, UDP_PORT))
sock.setblocking(False)

def draw_text_centered(screen, text, font, color, y):
    """A helper robot that paints words exactly in the middle of the screen."""
    surf = font.render(text, True, color)
    rect = surf.get_rect(center=(screen.get_width() // 2, y))
    screen.blit(surf, rect)

running = True
clock = pygame.time.Clock()

# This is our empty notebook. Before the DJ sends us real info, we show this:
data = {"scores": [], "time_left": 0, "song_name": "Waiting for DJ...", "num_players": 0}

# ==============================================================================
# --- THE MAIN PAINTING LOOP ---
# This runs round and round, 30 times a second, drawing a new picture every time!
# ==============================================================================
while running:
    # 1. Did the user press the X button or ask for Fullscreen?
    for event in pygame.event.get():
        if event.type == pygame.QUIT: 
            running = False
        # If you press the 'F' key on the keyboard, the TV goes FULLSCREEN!
        if event.type == pygame.KEYDOWN and event.key == pygame.K_f: 
            pygame.display.toggle_fullscreen()

    # ==============================================================================
    # 2. CHECK THE MAILBOX (READING NETWORK MESSAGES)
    # The DJ sends messages super fast! If we only read one message per frame, 
    # we will get behind (LAG!). So, we read ALL the messages in the mailbox 
    # as fast as possible until it's empty, and only keep the very newest one!
    # ==============================================================================
    try:
        while True:
            packet, _ = sock.recvfrom(2048) # Grab a message
            data = json.loads(packet.decode()) # Open the box and read the numbers
    except BlockingIOError:
        pass # The mailbox is empty, we are perfectly caught up!
    except Exception:
        pass # If a message is broken, just ignore it.

    # ==============================================================================
    # 3. PAINTING THE SCREEN
    # ==============================================================================
    
    # Paint the whole background a dark, space-like blue
    screen.fill((10, 10, 20)) 
    
    # Pick our fonts (Impact is a big, bold, superhero kind of font)
    f_title = pygame.font.SysFont("Impact", 45)
    f_score = pygame.font.SysFont("Impact", 65)
    f_timer = pygame.font.SysFont("Impact", 120)

    # --- Draw the Song Name ---
    # If the name is way too long, chop it off and add "..." so it fits on screen
    txt = data["song_name"][:50] + "..." if len(data["song_name"]) > 50 else data["song_name"]
    draw_text_centered(screen, txt, f_title, (0, 255, 255), 60) # Cyan color

    # --- Draw the Giant Clock ---
    # Convert seconds (like 125) into minutes and seconds (02:05)
    m, s = divmod(data["time_left"], 60)
    
    # If time is running out (less than 10 seconds), turn the clock RED to make it scary!
    # Otherwise, keep it WHITE.
    timer_color = (255, 255, 255) if data["time_left"] > 10 else (255, 50, 50)
    draw_text_centered(screen, f"{m:02d}:{s:02d}", f_timer, timer_color, 180)

    # --- Draw the Player Score Bars ---
    n = data["num_players"]
    if n > 0:
        # We want the bars to look perfectly centered like a tower.
        # We calculate how tall the tower is, and push it down the screen so it sits in the middle.
        bar_w = 900  # How wide is the bar?
        bar_h = 70   # How thick is the bar?
        spacing = 15 # Space between bars
        
        total_h = (n * bar_h) + ((n - 1) * spacing)
        start_y = 280 + ((screen.get_height() - 280) - total_h) // 2

        for i in range(n):
            y_pos = start_y + i * (bar_h + spacing)
            
            # Make a unique, beautiful rainbow color for each player
            color = [int(c*255) for c in colorsys.hsv_to_rgb(i/max(1.0, float(n)), 0.8, 1)] 
            
            # Draw the background of the player's box
            rect = pygame.Rect(0, y_pos, bar_w, bar_h)
            rect.centerx = screen.get_width() // 2
            
            pygame.draw.rect(screen, (30, 30, 45), rect, border_radius=15) # Dark gray box
            pygame.draw.rect(screen, color, rect, width=2, border_radius=15) # Glowing colored border

            # Write "PLAYER 1", "PLAYER 2" on the left side
            name = f_title.render(f"PLAYER {i+1}", True, (255, 255, 255))
            screen.blit(name, name.get_rect(midleft=(rect.left + 30, rect.centery)))
            
            # Write their giant score number on the right side
            score_val = str(data["scores"][i] if i < len(data["scores"]) else 0)
            sc = f_score.render(score_val, True, color)
            screen.blit(sc, sc.get_rect(midright=(rect.right - 30, rect.centery)))

    # Push the new painting to the screen!
    pygame.display.flip()
    
    # Wait a tiny bit before painting again (30 times a second)
    clock.tick(30)
    
# If the loop breaks (we clicked X), turn off the painting tools and go to sleep.
pygame.quit()