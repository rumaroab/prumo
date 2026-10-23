FROM ubuntu:22.04 AS build
RUN apt-get update && apt-get install -y --no-install-recommends build-essential gfortran git m4 \
    libnetcdf-dev libnetcdff-dev libopenmpi-dev openmpi-bin ca-certificates python3 python3-numpy python3-netcdf4 \
    && rm -rf /var/lib/apt/lists/*
RUN git clone https://github.com/openwfm/WRF-SFIRE.git /src/WRF-SFIRE \
    && cd /src/WRF-SFIRE && git checkout 9801186f3ef8a500ec106aecfdcb051c4d1e38db
COPY run-wrf-sfire /opt/forest-fire/run-wrf-sfire
COPY postprocess-wrf.py /opt/forest-fire/postprocess-wrf.py
RUN chmod +x /opt/forest-fire/run-wrf-sfire /opt/forest-fire/postprocess-wrf.py
# WRF configuration differs by compiler/MPI environment. Build and validate this image on the target runner,
# then publish it under the WRF_SFIRE_IMAGE name; the adapter records its digest in every result.
ENTRYPOINT []
