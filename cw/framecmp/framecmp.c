/*
 * framecmp — run a GBA ROM headless in libmgba with a scripted input movie and
 * print one CRC32 of the video buffer per frame (and optional PPM dumps).
 *
 * usage: framecmp ROM MOVIE FRAMES [DUMPDIR [EVERY]]
 *
 * MOVIE: lines "<start_frame> <length> <keys>", keys = A B SELECT START RIGHT LEFT UP DOWN R L
 *        joined with '+'. '#' starts a comment. Frames not covered press nothing.
 */
#include <mgba/core/core.h>
#include <mgba/core/log.h>
#include <mgba/core/config.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>
#include <zlib.h>

static void quietLog(struct mLogger* l, int c, enum mLogLevel lv, const char* f, va_list a) {
	(void) l; (void) c; (void) lv; (void) f; (void) a;
}
static struct mLogger quiet = { .log = quietLog };

struct Press { unsigned start, len, keys; };

static unsigned parseKeys(char* s) {
	static const char* names[] = { "A", "B", "SELECT", "START", "RIGHT", "LEFT", "UP", "DOWN", "R", "L" };
	unsigned k = 0;
	for (char* t = strtok(s, "+"); t; t = strtok(NULL, "+")) {
		int found = 0;
		for (int i = 0; i < 10; ++i) if (!strcmp(t, names[i])) { k |= 1u << i; found = 1; }
		if (!found) { fprintf(stderr, "unknown key %s\n", t); exit(2); }
	}
	return k;
}

int main(int argc, char** argv) {
	if (argc < 4) { fprintf(stderr, "usage: %s ROM MOVIE FRAMES [DUMPDIR [EVERY]]\n", argv[0]); return 2; }
	const char* rom = argv[1];
	unsigned frames = strtoul(argv[3], NULL, 0);
	const char* dumpDir = argc > 4 ? argv[4] : NULL;
	unsigned every = argc > 5 ? strtoul(argv[5], NULL, 0) : 60;

	struct Press presses[4096]; size_t n = 0;
	FILE* mf = fopen(argv[2], "r");
	if (!mf) { perror(argv[2]); return 2; }
	char line[256];
	while (fgets(line, sizeof line, mf) && n < 4096) {
		char* h = strchr(line, '#'); if (h) *h = 0;
		char keys[128];
		if (sscanf(line, "%u %u %127s", &presses[n].start, &presses[n].len, keys) == 3) {
			presses[n].keys = parseKeys(keys); ++n;
		}
	}
	fclose(mf);

	mLogSetDefaultLogger(&quiet);
	struct mCore* core = mCoreFind(rom);
	if (!core || !core->init(core)) { fprintf(stderr, "cannot init core\n"); return 1; }
	mCoreInitConfig(core, NULL);
	unsigned w, h;
	core->desiredVideoDimensions(core, &w, &h);
	color_t* buf = calloc((size_t) w * h, BYTES_PER_PIXEL);
	core->setVideoBuffer(core, buf, w);
	if (!mCoreLoadFile(core, rom)) { fprintf(stderr, "cannot load %s\n", rom); return 1; }
	core->reset(core);

	for (unsigned f = 0; f < frames; ++f) {
		unsigned keys = 0;
		for (size_t i = 0; i < n; ++i)
			if (f >= presses[i].start && f < presses[i].start + presses[i].len) keys |= presses[i].keys;
		core->setKeys(core, keys);
		core->runFrame(core);
		uLong crc = crc32(0, (const Bytef*) buf, (uInt) (w * h * BYTES_PER_PIXEL));
		printf("%u %08lx\n", f, crc);
		if (dumpDir && (f % every == 0 || f == frames - 1)) {
			char p[512]; snprintf(p, sizeof p, "%s/f%06u.ppm", dumpDir, f);
			FILE* o = fopen(p, "wb");
			if (o) {
				fprintf(o, "P6\n%u %u\n255\n", w, h);
				for (unsigned i = 0; i < w * h; ++i) {
					uint32_t c = buf[i];
					unsigned char rgb[3] = { c & 0xFF, (c >> 8) & 0xFF, (c >> 16) & 0xFF };
					fwrite(rgb, 1, 3, o);
				}
				fclose(o);
			}
		}
	}
	core->deinit(core);
	return 0;
}
