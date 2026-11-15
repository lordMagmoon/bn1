/*
 * framecmp2 — run two GBA ROMs side by side in libmgba with the same input movie and compare
 * every frame (RGB only).
 *
 * usage: framecmp2 ROM_A ROM_B MOVIE FRAMES [MAX_ROWS [MAX_RUN]]
 *
 * A frame "differs" when any pixel differs. Code that does the same work in a different number
 * of cycles can move a mid-frame video register write by a scanline ("tearing"), so a differing
 * frame is tolerated when at most MAX_ROWS rows differ (default 2) and at most MAX_RUN frames in
 * a row differ (default 1). Anything else (wider differences, or lag: consecutive differing
 * frames) fails. Exit status 0 = pass, 1 = fail.
 */
#include <mgba/core/core.h>
#include <mgba/core/log.h>
#include <mgba/core/config.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>

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

static struct mCore* boot(const char* rom, color_t** buf, unsigned* w, unsigned* h) {
	struct mCore* core = mCoreFind(rom);
	if (!core || !core->init(core)) { fprintf(stderr, "cannot init core for %s\n", rom); exit(2); }
	mCoreInitConfig(core, NULL);
	core->desiredVideoDimensions(core, w, h);
	*buf = calloc((size_t) *w * *h, BYTES_PER_PIXEL);
	core->setVideoBuffer(core, *buf, *w);
	if (!mCoreLoadFile(core, rom)) { fprintf(stderr, "cannot load %s\n", rom); exit(2); }
	core->reset(core);
	return core;
}

int main(int argc, char** argv) {
	if (argc < 5) { fprintf(stderr, "usage: %s ROM_A ROM_B MOVIE FRAMES [MAX_ROWS [MAX_RUN]]\n", argv[0]); return 2; }
	unsigned frames = strtoul(argv[4], NULL, 0);
	unsigned maxRows = argc > 5 ? strtoul(argv[5], NULL, 0) : 2;
	unsigned maxRun = argc > 6 ? strtoul(argv[6], NULL, 0) : 1;

	struct Press presses[4096]; size_t n = 0;
	FILE* mf = fopen(argv[3], "r");
	if (!mf) { perror(argv[3]); return 2; }
	char line[256];
	while (fgets(line, sizeof line, mf) && n < 4096) {
		char* hsh = strchr(line, '#'); if (hsh) *hsh = 0;
		char keys[128];
		if (sscanf(line, "%u %u %127s", &presses[n].start, &presses[n].len, keys) == 3) {
			presses[n].keys = parseKeys(keys); ++n;
		}
	}
	fclose(mf);

	mLogSetDefaultLogger(&quiet);
	color_t *ba, *bb; unsigned w, h, w2, h2;
	struct mCore* a = boot(argv[1], &ba, &w, &h);
	struct mCore* b = boot(argv[2], &bb, &w2, &h2);

	unsigned differing = 0, tolerated = 0, run = 0, worstRows = 0, failFrame = 0;
	int fail = 0;
	for (unsigned f = 0; f < frames; ++f) {
		unsigned keys = 0;
		for (size_t i = 0; i < n; ++i)
			if (f >= presses[i].start && f < presses[i].start + presses[i].len) keys |= presses[i].keys;
		a->setKeys(a, keys); b->setKeys(b, keys);
		a->runFrame(a); b->runFrame(b);
		unsigned rows = 0, first = 0, last = 0;
		for (unsigned y = 0; y < h; ++y) {
			int d = 0;
			for (unsigned x = 0; x < w && !d; ++x)
				d = ((ba[y * w + x] ^ bb[y * w + x]) & 0x00FFFFFF) != 0;
			if (d) { if (!rows) first = y; last = y; ++rows; }
		}
		if (!rows) { run = 0; continue; }
		++differing; ++run;
		if (rows > worstRows) worstRows = rows;
		int ok = rows <= maxRows && run <= maxRun;
		printf("frame %u: %u rows differ (%u..%u)%s\n", f, rows, first, last, ok ? " [tolerated: timing]" : " [FAIL]");
		if (ok) ++tolerated;
		else if (!fail) { fail = 1; failFrame = f; }
	}
	printf("%u frames compared: %u identical, %u tolerated (<= %u rows, isolated), %u failing; worst %u rows\n",
	       frames, frames - differing, tolerated, maxRows, differing - tolerated, worstRows);
	if (fail) printf("FIRST FAILING FRAME: %u\n", failFrame);
	a->deinit(a); b->deinit(b);
	return fail ? 1 : 0;
}
