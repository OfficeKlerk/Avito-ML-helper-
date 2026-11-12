FROM python:3.12-slim
WORKDIR /srv
COPY --from=agent requirements.txt /tmp/agent-requirements.txt
COPY --from=knowledge requirements.txt /tmp/knowledge-requirements.txt
RUN pip install --no-cache-dir -r /tmp/agent-requirements.txt -r /tmp/knowledge-requirements.txt
COPY --from=agent app ./agent/app
COPY --from=agent prompts ./agent/prompts
COPY --from=knowledge app ./knowledge-service/app
COPY contracts ./contracts
COPY fixtures ./fixtures
COPY data ./data
COPY integration/knowledge_agent.py ./integration/knowledge_agent.py
CMD ["python", "integration/knowledge_agent.py"]
