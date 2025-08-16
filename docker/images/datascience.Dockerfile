# Data science environment with common ML libraries
FROM python:3.11

# Install data science packages
RUN pip install --no-cache-dir \
    numpy==1.24.3 \
    pandas==2.0.3 \
    scikit-learn==1.3.0 \
    matplotlib==3.7.2 \
    seaborn==0.12.2 \
    jupyter==1.0.0

# Install additional ML frameworks (optional)
# RUN pip install tensorflow torch

WORKDIR /workspace

CMD ["python"]
