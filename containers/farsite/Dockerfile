FROM ubuntu:22.04 AS build
RUN apt-get update && apt-get install -y --no-install-recommends build-essential ca-certificates git \
    && rm -rf /var/lib/apt/lists/*
# Modern GCC rejects a redundant pointer-to-integer comparison in this pinned
# legacy source. The replacement preserves the intended null-pointer check.
RUN git clone https://github.com/mbedward/farsite.git /src/farsite \
    && cd /src/farsite && git checkout 4537d60ab013fa91d0b49d8efb385ffb1b3ddd13 \
    && sed -i 's/-Wno-deprecated/-Wno-deprecated -Wno-narrowing/' src/Makefile \
    && sed -i 's/perimeter1\[NumFire\] && perimeter1\[NumFire\] > 0/perimeter1[NumFire]/' src/Farsite5.cpp \
    && make -C src
# The image is enabled only if the pinned executable completes the repository's
# documented flatland case and emits a non-empty perimeter shapefile.
RUN cd /src/farsite \
    && sed -i 's|$scriptRoot|/src|g' \
       examples/flatland/caseRunFiles/centerIgnit/b_RAWS/singleWinds/run_flatland_centerIgnit_3mph0deg7hr_RAWS.txt \
       examples/flatland/Inputs/c_inputSpecFiles/flatland_3mph0deg7hr_RAWS.input \
    && find examples/flatland/Outputs/centerIgnit/b_RAWS/singleWinds/flatland_centerIgnit_3mph0deg7hr_RAWS -type f -delete \
    && (./src/TestFARSITE examples/flatland/caseRunFiles/centerIgnit/b_RAWS/singleWinds/run_flatland_centerIgnit_3mph0deg7hr_RAWS.txt \
       > /tmp/flatland-smoke.log 2>&1 || { cat /tmp/flatland-smoke.log; exit 1; }) \
    && (test -s examples/flatland/Outputs/centerIgnit/b_RAWS/singleWinds/flatland_centerIgnit_3mph0deg7hr_RAWS/flatland_centerIgnit_3mph0deg7hr_RAWS_Perimeters.shp \
       || { cat /tmp/flatland-smoke.log; exit 1; })

FROM ubuntu:22.04
COPY --from=build /src/farsite/src/TestFARSITE /opt/farsite/TestFARSITE
ENTRYPOINT []
