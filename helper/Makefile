CC ?= cc
CFLAGS ?= -std=c17 -O2 -Wall -Wextra -Werror

all: recoll-membership

recoll-membership: recoll_membership.c
	$(CC) $(CFLAGS) $< -o $@

clean:
	rm -f recoll-membership

.PHONY: all clean
