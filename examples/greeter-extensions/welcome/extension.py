"""Welcome branding for the Dev OS login screen (greeter extension)."""
import socket
import time


def activate(api):
    api.set_subtitle('Sign in to your desktop')

    def background(painter):
        painter.text(time.strftime('%H:%M'), 48, 96, 'dim', 42, True)
        painter.text(socket.gethostname(), 48, 128, 'dim', 13)
        painter.rect(48, painter.height - 72, 220, 2, 'line')
        painter.text('Dev OS', 48, painter.height - 44, 'dim', 11)

    api.paint_background(background)
