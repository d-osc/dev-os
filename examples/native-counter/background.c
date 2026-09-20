#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include <unistd.h>

int main(void) {
    const char *data = getenv("DEVOS_DATA_DIR");
    if (!data || chdir(data) != 0) return 1;
    unsigned long ticks = 0;
    FILE *file = fopen("counter.json", "r");
    if (file) {
        if (fscanf(file, "{\"ticks\": %lu", &ticks) != 1) ticks = 0;
        fclose(file);
    }
    for (;;) {
        file = fopen("counter.new", "w");
        if (!file) return 1;
        if (fprintf(file, "{\"ticks\": %lu, \"updated\": %lld}\n", ++ticks,
                    (long long)time(NULL)) < 0) { fclose(file); return 1; }
        if (fclose(file) != 0 || rename("counter.new", "counter.json") != 0) return 1;
        sleep(1);
    }
}
