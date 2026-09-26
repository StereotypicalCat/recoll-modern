#define _POSIX_C_SOURCE 200809L

#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

#define MAX_FIELD (16u * 1024u * 1024u)

static uint32_t read_u32(const unsigned char *bytes) {
    return ((uint32_t)bytes[0] << 24) | ((uint32_t)bytes[1] << 16) |
           ((uint32_t)bytes[2] << 8) | (uint32_t)bytes[3];
}

static int error(const char *message) {
    fprintf(stderr, "recoll-membership: %s\n", message);
    return 1;
}

int main(int argc, char **argv) {
    const char *map_path = getenv("RECOLL_MODERN_MEMBERSHIP_MAP");
    if (argc != 2 || map_path == NULL || map_path[0] == '\0') {
        return error("map or file path is missing");
    }
    FILE *stream = fopen(map_path, "rb");
    if (stream == NULL) {
        return error("map is unreadable");
    }
    struct stat info;
    if (fstat(fileno(stream), &info) != 0 || info.st_size < 4 ||
        (uintmax_t)info.st_size > SIZE_MAX) {
        fclose(stream);
        return error("map is corrupt");
    }
    size_t size = (size_t)info.st_size;
    unsigned char *data = malloc(size);
    if (data == NULL || fread(data, 1, size, stream) != size) {
        free(data);
        fclose(stream);
        return error("map is unreadable");
    }
    fclose(stream);
    if (memcmp(data, "RCM1", 4) != 0) {
        free(data);
        return error("map is corrupt");
    }
    const unsigned char *match = NULL;
    size_t match_length = 0;
    size_t path_length = strlen(argv[1]);
    size_t offset = 4;
    while (offset < size) {
        if (size - offset < 4) {
            free(data);
            return error("map is corrupt");
        }
        size_t key_length = read_u32(data + offset);
        offset += 4;
        if (key_length > MAX_FIELD || key_length > size - offset) {
            free(data);
            return error("map is corrupt");
        }
        const unsigned char *key = data + offset;
        offset += key_length;
        if (size - offset < 4) {
            free(data);
            return error("map is corrupt");
        }
        size_t value_length = read_u32(data + offset);
        offset += 4;
        if (value_length > MAX_FIELD || value_length > size - offset) {
            free(data);
            return error("map is corrupt");
        }
        if (key_length == path_length && memcmp(key, argv[1], path_length) == 0) {
            match = data + offset;
            match_length = value_length;
        }
        offset += value_length;
    }
    if (match != NULL && match_length != 0) {
        if (fwrite(match, 1, match_length, stdout) != match_length || putchar('\n') == EOF) {
            free(data);
            return error("output failed");
        }
    }
    free(data);
    return 0;
}
