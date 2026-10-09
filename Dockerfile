FROM python:3.12-slim

WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# Baza lezy na wolumenie, zeby przezyla przebudowe obrazu.
ENV TELEMETRY_DB=/data/recordings.db
VOLUME ["/data"]

# Port WEWNATRZ kontenera. Sama liczba jest dowolna, ale MUSI zgadzac sie
# z polem "Service URL" tunelu (http://telemetry:8988) - tunel idzie siecia
# composa prosto do kontenera i o mapowaniu na hosta nic nie wie.
#
# Jesli port na HOSCIE koliduje z czyms innym, zmien HOST_PORT w .env.
# Tych dwoch linii nie ruszaj bez rownoczesnej zmiany Service URL.
#
# EXPOSE nie robi nic poza dokumentacja; zostaje dla czytelnosci.
EXPOSE 8988
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8988"]
