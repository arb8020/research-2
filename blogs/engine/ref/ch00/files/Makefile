# The chapter's C++ build (cstyle_cpp.md "Build"): one tree per profile, never mixed.
#   debug    -O0 -g, ASSERTs on, ASan + UBSan that stop at the first report: every check uses this
#   release  -O2 -g, ASSERTs still on: perf checks (later chapters)
# Objects live in build/$(PROFILE)/, so an edit to one .cpp rebuilds one object and the link.
PROFILE ?= debug
CXX := g++
OUT := build/$(PROFILE)
WARN := -Wall -Wextra -Werror -Wshadow -Wconversion -Wsign-conversion
HARDEN := -fno-exceptions -fno-rtti
SAN := -fsanitize=address,undefined -fno-sanitize-recover=all -fno-omit-frame-pointer
ifeq ($(PROFILE),debug)
  OPT := -O0 -g $(SAN)
  LDFLAGS := $(SAN)
else ifeq ($(PROFILE),release)
  OPT := -O2 -g
  LDFLAGS :=
else
  $(error PROFILE must be debug or release, got $(PROFILE))
endif
CXXFLAGS := -std=c++20 $(WARN) $(HARDEN) -MMD -MP $(OPT)

$(OUT)/check_ring: $(OUT)/ring.o $(OUT)/check_ring.o
	$(CXX) $(LDFLAGS) -o $@ $^

$(OUT)/check_trace: $(OUT)/ring.o $(OUT)/loop.o $(OUT)/check_trace.o
	$(CXX) $(LDFLAGS) -o $@ $^

$(OUT)/%.o: %.cpp | $(OUT)
	$(CXX) $(CXXFLAGS) -c $< -o $@

$(OUT):
	mkdir -p $@

clean:
	rm -rf build

.PHONY: clean
-include $(wildcard $(OUT)/*.d)
