FROM python:3.12-slim
RUN pip install --no-cache-dir quicfire-tools==0.11.0 numpy
COPY run-quicfire.py /opt/forest-fire/run-quicfire
RUN chmod +x /opt/forest-fire/run-quicfire
RUN python -m py_compile /opt/forest-fire/run-quicfire \
    && python -c "from pathlib import Path; from quicfire_tools import SimulationInputs; p=Path('/tmp/qf-smoke'); SimulationInputs.create_simulation(2,2,1,1.0,270,60).write_inputs(p); assert any(p.iterdir())"
ENTRYPOINT []
