#include <X11/Xlib.h>
#include <X11/Xutil.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

extern const char *app_title(void);

static void label(Display *display, Window window, GC gc, int x, int y,
                  const char *text, unsigned long color) {
    XSetForeground(display, gc, color);
    XDrawString(display, window, gc, x, y, text, (int)strlen(text));
}

static void screenshot(Display *display, Window window) {
    XImage *image = XGetImage(display, window, 0, 0, 560, 320, AllPlanes, ZPixmap);
    if (!image) return;
    FILE *file = fopen("window.ppm", "wb");
    if (file) {
        fprintf(file, "P6\n560 320\n255\n");
        for (int y = 0; y < 320; y++) for (int x = 0; x < 560; x++) {
            unsigned long p = XGetPixel(image, x, y);
            unsigned char rgb[] = {(p >> 16) & 255, (p >> 8) & 255, p & 255};
            fwrite(rgb, 1, sizeof(rgb), file);
        }
        fclose(file);
    }
    XDestroyImage(image);
}

int main(int argc, char **argv) {
    const char *data = getenv("DEVOS_DATA_DIR");
    if (!data || chdir(data) != 0) return 1;
    Display *display = XOpenDisplay(NULL);
    if (!display) { fputs("Cannot open X11 desktop\n", stderr); return 1; }
    Window window = XCreateSimpleWindow(display, DefaultRootWindow(display), 80, 80,
                                        560, 320, 0, 0, 0x142034);
    XStoreName(display, window, app_title());
    Atom close_atom = XInternAtom(display, "WM_DELETE_WINDOW", False);
    XSetWMProtocols(display, window, &close_atom, 1);
    XSelectInput(display, window, ExposureMask | ButtonPressMask);
    XMapWindow(display, window);
    GC gc = XCreateGC(display, window, 0, NULL);
    int running = 1, captured = 0;
    int testing = argc > 1 && strcmp(argv[1], "--test") == 0;
    time_t started = time(NULL);
    while (running) {
        while (XPending(display)) {
            XEvent event;
            XNextEvent(display, &event);
            if (event.type == ClientMessage && (Atom)event.xclient.data.l[0] == close_atom) running = 0;
            if (event.type == ButtonPress && event.xbutton.x >= 28 && event.xbutton.x <= 220 &&
                event.xbutton.y >= 250 && event.xbutton.y <= 286) running = 0;
        }
        XSetForeground(display, gc, 0x142034);
        XFillRectangle(display, window, gc, 0, 0, 560, 320);
        label(display, window, gc, 28, 40, "DEV OS / LINUX BINARY", 0x65e0bf);
        label(display, window, gc, 28, 78, app_title(), 0xe5edf8);
        unsigned long ticks = 0;
        long long updated = 0;
        FILE *file = fopen("counter.json", "r");
        int valid = file && fscanf(file, "{\"ticks\": %lu, \"updated\": %lld}", &ticks, &updated) == 2;
        if (file) fclose(file);
        label(display, window, gc, 28, 122,
              valid && time(NULL) - updated < 3 ? "Background: Running (static ELF)" : "Background: Stopped",
              0xe5edf8);
        char text[80];
        snprintf(text, sizeof(text), "Counter: %lu", ticks);
        label(display, window, gc, 28, 158, text, 0x65e0bf);
        label(display, window, gc, 28, 200, "Window: dynamic ELF + packaged shared library", 0xe5edf8);
        label(display, window, gc, 28, 224, "No Python, Node or Bash interpreter required.", 0xe5edf8);
        XSetForeground(display, gc, 0x28425e);
        XFillRectangle(display, window, gc, 28, 250, 192, 36);
        label(display, window, gc, 50, 273, "Close window", 0xe5edf8);
        XSync(display, False);
        if (testing && !captured && time(NULL) - started >= 2) {
            screenshot(display, window); captured = 1;
        }
        if (testing && time(NULL) - started >= 4) running = 0;
        usleep(100000);
    }
    XFreeGC(display, gc);
    XDestroyWindow(display, window);
    XCloseDisplay(display);
    return 0;
}
