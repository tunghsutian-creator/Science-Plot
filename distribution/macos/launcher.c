#include <errno.h>
#include <limits.h>
#include <mach-o/dyld.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

/* Finder needs a native executable. All plotting remains in the public CLI. */
int main(int argc, char **argv) {
    char executable[PATH_MAX];
    char resolved[PATH_MAX];
    uint32_t size = sizeof(executable);
    if (_NSGetExecutablePath(executable, &size) != 0 || !realpath(executable, resolved)) {
        perror("SciPlot: cannot locate this application");
        return 1;
    }
    char *slash = strrchr(resolved, '/');
    if (!slash || (size_t)(slash - resolved) + sizeof("/sciplot") > sizeof(resolved)) {
        fputs("SciPlot: invalid application path\n", stderr);
        return 1;
    }
    strcpy(slash, "/sciplot");
    char **arguments = calloc((size_t)argc + 2, sizeof(char *));
    if (!arguments) {
        perror("SciPlot");
        return 1;
    }
    arguments[0] = resolved;
    arguments[1] = "--welcome";
    for (int index = 1; index < argc; ++index) arguments[index + 1] = argv[index];
    execv(resolved, arguments);
    perror("SciPlot: cannot start bundled runtime");
    free(arguments);
    return 1;
}
