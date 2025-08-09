#!/usr/bin/env python3
"""
Example External ML Service

Demonstrates how to create an external service that integrates with Gleitzeit
via Socket.IO to handle ML training and inference tasks.

This service:
1. Registers with Gleitzeit cluster as an ML service
2. Handles ML training and inference requests
3. Reports progress and results back to the cluster
4. Integrates seamlessly with workflow dependencies
"""

import asyncio
import json
import sys
import time
import numpy as np
from pathlib import Path
from sklearn.ensemble import RandomForestClassifier
from sklearn.datasets import make_classification
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score

# Add the parent directory to the path so we can import gleitzeit_cluster
sys.path.insert(0, str(Path(__file__).parent.parent))

from gleitzeit_cluster.core.external_service_node import ExternalServiceNode, ExternalServiceCapability


class MockMLService:
    """Mock ML service for demonstration purposes"""
    
    def __init__(self):
        self.models = {}  # Store trained models
        
    async def train_model(self, task_data: dict) -> dict:
        """Handle ML training request"""
        print(f"🧠 Training ML model...")
        
        # Extract parameters
        parameters = task_data.get('parameters', {})
        external_params = parameters.get('external_parameters', {})
        model_params = external_params.get('model_params', {})
        data_params = external_params.get('data_params', {})
        
        # Generate mock dataset
        n_samples = data_params.get('n_samples', 1000)
        n_features = data_params.get('n_features', 10)
        n_classes = data_params.get('n_classes', 2)
        
        print(f"   Generating dataset: {n_samples} samples, {n_features} features, {n_classes} classes")
        
        # Simulate training time
        await asyncio.sleep(2)
        
        X, y = make_classification(
            n_samples=n_samples,
            n_features=n_features,
            n_classes=n_classes,
            n_informative=max(2, n_features // 2),
            n_redundant=0,
            random_state=42
        )
        
        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
        
        # Train model
        model_type = model_params.get('model_type', 'random_forest')
        n_estimators = model_params.get('n_estimators', 100)
        
        print(f"   Training {model_type} with {n_estimators} estimators...")
        
        model = RandomForestClassifier(n_estimators=n_estimators, random_state=42)
        model.fit(X_train, y_train)
        
        # Evaluate
        y_pred = model.predict(X_test)
        accuracy = accuracy_score(y_test, y_pred)
        
        # Store model
        model_id = f"model_{int(time.time())}"
        self.models[model_id] = {
            'model': model,
            'accuracy': accuracy,
            'n_features': n_features,
            'n_classes': n_classes,
            'trained_at': time.time()
        }
        
        print(f"   ✅ Model trained! ID: {model_id}, Accuracy: {accuracy:.3f}")
        
        return {
            'model_id': model_id,
            'accuracy': float(accuracy),
            'n_samples_train': len(X_train),
            'n_samples_test': len(X_test),
            'n_features': n_features,
            'n_classes': n_classes,
            'model_type': model_type,
            'training_completed_at': time.time()
        }
    
    async def run_inference(self, task_data: dict) -> dict:
        """Handle ML inference request"""
        print(f"🔮 Running ML inference...")
        
        # Extract parameters
        parameters = task_data.get('parameters', {})
        external_params = parameters.get('external_parameters', {})
        
        model_id = external_params.get('model_id')
        if not model_id or model_id not in self.models:
            raise ValueError(f"Model {model_id} not found")
        
        model_info = self.models[model_id]
        model = model_info['model']
        
        # Generate test data (in real service, this would come from the request)
        n_samples = external_params.get('n_samples', 100)
        n_features = model_info['n_features']
        
        print(f"   Generating {n_samples} samples for inference...")
        
        # Simulate inference time
        await asyncio.sleep(1)
        
        X_inference = np.random.randn(n_samples, n_features)
        predictions = model.predict(X_inference)
        probabilities = model.predict_proba(X_inference)
        
        print(f"   ✅ Inference completed! {n_samples} predictions made")
        
        return {
            'model_id': model_id,
            'n_samples': n_samples,
            'predictions': predictions.tolist(),
            'prediction_probabilities': probabilities.tolist(),
            'inference_completed_at': time.time()
        }
    
    async def evaluate_model(self, task_data: dict) -> dict:
        """Handle model evaluation request"""
        print(f"📊 Evaluating ML model...")
        
        parameters = task_data.get('parameters', {})
        external_params = parameters.get('external_parameters', {})
        
        model_id = external_params.get('model_id')
        if not model_id or model_id not in self.models:
            raise ValueError(f"Model {model_id} not found")
        
        model_info = self.models[model_id]
        
        # Simulate evaluation time
        await asyncio.sleep(1)
        
        # Return stored accuracy and additional metrics
        return {
            'model_id': model_id,
            'accuracy': model_info['accuracy'],
            'model_age_seconds': time.time() - model_info['trained_at'],
            'n_features': model_info['n_features'],
            'n_classes': model_info['n_classes'],
            'evaluation_completed_at': time.time()
        }


async def main():
    """Main entry point for external ML service"""
    print("🚀 Starting External ML Service")
    print("=" * 50)
    
    # Create ML service instance
    ml_service = MockMLService()
    
    # Create external service node
    service_node = ExternalServiceNode(
        service_name="Mock ML Service",
        cluster_url="http://localhost:8000",
        capabilities=[
            ExternalServiceCapability.ML_TRAINING,
            ExternalServiceCapability.ML_INFERENCE
        ],
        max_concurrent_tasks=5,
        heartbeat_interval=15
    )
    
    # Register task handlers
    service_node.register_task_handler("ml_training", ml_service.train_model)
    service_node.register_task_handler("ml_inference", ml_service.run_inference) 
    service_node.register_task_handler("external_ml", ml_service.train_model)  # Generic handler
    
    # Register operation-specific handlers
    async def handle_ml_task(task_data: dict):
        """Route ML tasks based on operation type"""
        parameters = task_data.get('parameters', {})
        external_params = parameters.get('external_parameters', {})
        operation = external_params.get('operation', 'train')
        
        if operation == 'train':
            return await ml_service.train_model(task_data)
        elif operation == 'inference':
            return await ml_service.run_inference(task_data)
        elif operation == 'evaluate':
            return await ml_service.evaluate_model(task_data)
        else:
            raise ValueError(f"Unknown ML operation: {operation}")
    
    # Register the unified handler
    service_node.register_task_handler("ml_training", handle_ml_task)
    service_node.register_task_handler("ml_inference", handle_ml_task)
    
    print("📋 Registered task handlers:")
    print("   - ml_training (supports: train, evaluate)")
    print("   - ml_inference (supports: inference)")
    print("   - external_ml (generic ML tasks)")
    
    try:
        print(f"\\n🔌 Connecting to Gleitzeit cluster at http://localhost:8000")
        await service_node.start()
    except KeyboardInterrupt:
        print("\\n🛑 Interrupted by user")
    except Exception as e:
        print(f"💥 Service failed: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print("\\n🧹 Cleaning up...")
        await service_node.stop()


if __name__ == "__main__":
    # Check dependencies
    try:
        import sklearn
        import numpy
    except ImportError as e:
        print(f"❌ Missing dependency: {e}")
        print("💡 Install with: pip install scikit-learn numpy")
        sys.exit(1)
    
    print("💡 Make sure Gleitzeit cluster is running:")
    print("   Terminal 1: python examples/monitoring_demo.py")
    print("   Terminal 2: python examples/external_ml_service.py")
    print("   Terminal 3: python examples/external_task_demo.py")
    print()
    
    asyncio.run(main())