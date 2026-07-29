# arianna — the body. Pure C, no external deps beyond libm/pthread (+OpenMP if present).
# Linux (polygon-class):  make            -> -O3 -march=native -fopenmp
# macOS (Apple Silicon):  make            -> clang + Homebrew libomp if installed

UNAME_S := $(shell uname -s)

ifeq ($(UNAME_S),Darwin)
CC      = clang
OMPDIR := $(shell brew --prefix libomp 2>/dev/null)
ifneq ($(OMPDIR),)
OMPC    = -Xclang -fopenmp -I$(OMPDIR)/include
OMPL    = -L$(OMPDIR)/lib -lomp
endif
CFLAGS  = -O3 $(OMPC) -Wall -Wextra -Wno-unused-parameter -Wno-misleading-indentation -Wno-unused-function
LDFLAGS = -lm $(OMPL) -lpthread
else
CC      = gcc
ARCH   ?= native
CFLAGS  = -O3 -march=$(ARCH) -fopenmp -Wall -Wextra -Wno-unused-parameter -Wno-misleading-indentation -Wno-unused-function
LDFLAGS = -lm -fopenmp -lpthread
endif

NT = vendor/notorch

arianna: arianna.c st.h json.h qwen_tok.h $(NT)/notorch.o
	$(CC) $(CFLAGS) -I$(NT) arianna.c $(NT)/notorch.o -o arianna $(LDFLAGS)

$(NT)/notorch.o: $(NT)/notorch.c $(NT)/notorch.h
	$(CC) $(CFLAGS) -I$(NT) -c $(NT)/notorch.c -o $@

tests/q4kprobe: tests/q4kprobe.c st.h json.h $(NT)/notorch.o
	$(CC) $(CFLAGS) -I. -I$(NT) tests/q4kprobe.c $(NT)/notorch.o -o $@ $(LDFLAGS)

tests/q6probe: tests/q6probe.c st.h json.h $(NT)/notorch.o
	$(CC) $(CFLAGS) -I. -I$(NT) tests/q6probe.c $(NT)/notorch.o -o $@ $(LDFLAGS)

tests/bw: tests/bw.c
	$(CC) $(CFLAGS) tests/bw.c -o $@ $(LDFLAGS)

clean:
	rm -f arianna $(NT)/notorch.o tests/q4kprobe tests/q6probe tests/bw

.PHONY: clean
