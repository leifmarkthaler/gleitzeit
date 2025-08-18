"""
Demo script for Instructor integration with Gleitzeit

This demonstrates how to use the InstructorProvider for structured LLM outputs.
"""

import asyncio
import json
from typing import List, Optional
from pydantic import BaseModel, Field

from gleitzeit.experimental.instructor import InstructorProvider
from gleitzeit.experimental.instructor.models import SchemaDefinition


# Example Pydantic models for structured outputs
class Person(BaseModel):
    """Person information model"""
    name: str = Field(..., description="Full name of the person")
    age: int = Field(..., ge=0, le=150, description="Age in years")
    email: str = Field(..., regex=r'^[\w\.-]+@[\w\.-]+\.\w+$', description="Email address")
    occupation: Optional[str] = Field(None, description="Current occupation")


class ProductReview(BaseModel):
    """Product review model"""
    product_name: str
    rating: float = Field(..., ge=0, le=5)
    pros: List[str] = Field(default_factory=list)
    cons: List[str] = Field(default_factory=list)
    would_recommend: bool
    summary: str = Field(..., max_length=500)


class TaskOutput(BaseModel):
    """Structured task output"""
    task_id: str
    status: str = Field(..., regex='^(pending|in_progress|completed|failed)$')
    result: Optional[dict] = None
    error: Optional[str] = None
    metadata: dict = Field(default_factory=dict)


async def demo_basic_extraction():
    """Demonstrate basic information extraction"""
    print("\n=== Basic Information Extraction ===")
    
    provider = InstructorProvider(
        default_provider="openai",
        default_model="gpt-3.5-turbo"
    )
    
    # Note: This will fail without actual API keys and instructor installed
    # This is just to demonstrate the API
    
    try:
        await provider.initialize()
        
        # Extract person information
        result = await provider.execute("llm/structured", {
            "schema": Person.model_json_schema(),
            "messages": [
                {"role": "system", "content": "Extract person information from the text."},
                {"role": "user", "content": "John Smith is a 35-year-old software engineer. Contact him at john.smith@techcorp.com"}
            ]
        })
        
        print(f"Extracted Person: {json.dumps(result['data'], indent=2)}")
        
    except Exception as e:
        print(f"Demo failed (expected without API keys): {e}")
    finally:
        await provider.shutdown()


async def demo_product_review_extraction():
    """Demonstrate product review extraction"""
    print("\n=== Product Review Extraction ===")
    
    provider = InstructorProvider()
    
    try:
        await provider.initialize()
        
        review_text = """
        I recently bought the TechPro X1 laptop and I'm mostly satisfied. 
        The performance is excellent - it handles all my development tasks smoothly.
        The 16GB RAM and fast SSD make multitasking a breeze. Battery life is 
        impressive at 10+ hours. However, it's quite heavy at 2.5kg, making it 
        less portable than I'd like. The keyboard feels a bit mushy too. 
        Overall, I'd give it 4 out of 5 stars and would recommend it for 
        developers who don't travel much.
        """
        
        result = await provider.execute("llm/extract", {
            "text": review_text,
            "schema": ProductReview.model_json_schema(),
            "provider": "openai",
            "model": "gpt-4"
        })
        
        print(f"Extracted Review: {json.dumps(result['data'], indent=2)}")
        
    except Exception as e:
        print(f"Demo failed (expected without API keys): {e}")
    finally:
        await provider.shutdown()


async def demo_text_classification():
    """Demonstrate text classification"""
    print("\n=== Text Classification ===")
    
    provider = InstructorProvider()
    
    try:
        await provider.initialize()
        
        texts = [
            "This product exceeded all my expectations! Absolutely love it!",
            "The service was terrible and the product broke after one day.",
            "It's okay, nothing special but does the job.",
            "Has some good features but also several annoying issues."
        ]
        
        for text in texts:
            result = await provider.execute("llm/classify", {
                "text": text,
                "categories": ["positive", "negative", "neutral", "mixed"],
                "provider": "openai"
            })
            
            print(f"\nText: '{text[:50]}...'" if len(text) > 50 else f"\nText: '{text}'")
            print(f"Classification: {result['data']['category']}")
            
    except Exception as e:
        print(f"Demo failed (expected without API keys): {e}")
    finally:
        await provider.shutdown()


async def demo_schema_from_dict():
    """Demonstrate creating schema from dictionary"""
    print("\n=== Schema from Dictionary ===")
    
    # Define schema as dictionary (like in YAML workflows)
    schema_dict = {
        "name": "Meeting",
        "properties": {
            "title": {
                "type": "string",
                "description": "Meeting title"
            },
            "date": {
                "type": "string",
                "format": "date-time",
                "description": "Meeting date and time"
            },
            "attendees": {
                "type": "array",
                "items": {
                    "type": "string"
                },
                "description": "List of attendee names"
            },
            "duration_minutes": {
                "type": "integer",
                "minimum": 15,
                "maximum": 480,
                "description": "Meeting duration in minutes"
            },
            "is_virtual": {
                "type": "boolean",
                "description": "Whether the meeting is virtual"
            }
        },
        "required": ["title", "date", "attendees"]
    }
    
    # Convert to SchemaDefinition
    schema = SchemaDefinition.from_dict(schema_dict)
    
    # Convert to Pydantic model
    MeetingModel = schema.to_pydantic_model()
    
    # Test the model
    meeting = MeetingModel(
        title="Product Planning",
        date="2024-01-15T14:00:00",
        attendees=["Alice", "Bob", "Charlie"],
        duration_minutes=60,
        is_virtual=True
    )
    
    print(f"Created meeting: {meeting.model_dump()}")
    
    # Show how it would be used with the provider
    provider = InstructorProvider()
    
    print("\nSchema can be used with provider for structured generation:")
    print(f"  await provider.execute('llm/structured', {{")
    print(f"      'schema': {json.dumps(schema_dict, indent=8)},")
    print(f"      'messages': [...]")
    print(f"  }})")


async def demo_workflow_integration():
    """Show how Instructor integrates with Gleitzeit workflows"""
    print("\n=== Workflow Integration Example ===")
    
    workflow_example = """
# In a Gleitzeit workflow YAML file:
    
name: "Data Extraction Pipeline"
tasks:
  - id: "extract_contact"
    method: "llm/structured"
    parameters:
      provider: "openai"
      model: "gpt-3.5-turbo"
      schema:
        name: "ContactInfo"
        properties:
          name: {type: "string"}
          email: {type: "string", format: "email"}
          phone: {type: "string"}
          company: {type: "string"}
        required: ["name", "email"]
      messages:
        - role: "user"
          content: "Extract contact: Jane Doe from Acme Corp, jane@acme.com, 555-0123"
  
  - id: "classify_urgency"
    method: "llm/classify"
    dependencies: ["extract_contact"]
    parameters:
      text: "URGENT: Contract expires tomorrow! Need signature ASAP!"
      categories: ["low", "medium", "high", "critical"]
  
  - id: "create_task"
    method: "llm/structured"
    dependencies: ["extract_contact", "classify_urgency"]
    parameters:
      schema:
        name: "Task"
        properties:
          title: {type: "string"}
          assignee: {type: "string"}
          priority: {type: "string"}
          due_date: {type: "string", format: "date"}
          contact_email: {type: "string"}
      messages:
        - role: "system"
          content: "Create a task based on the extracted information"
        - role: "user"  
          content: |
            Contact: ${extract_contact.data.name}
            Company: ${extract_contact.data.company}
            Email: ${extract_contact.data.email}
            Urgency: ${classify_urgency.data.category}
            Action: Review and sign contract
    """
    
    print(workflow_example)
    print("\nThis workflow:")
    print("1. Extracts structured contact information")
    print("2. Classifies the urgency level")
    print("3. Creates a structured task with all the information")
    print("\nAll outputs are validated and typed using Pydantic models!")


async def main():
    """Run all demos"""
    print("=" * 60)
    print("Instructor Provider Demo for Gleitzeit")
    print("=" * 60)
    
    # Note: These demos will fail without actual API keys
    # They're designed to show the API and usage patterns
    
    await demo_schema_from_dict()
    await demo_workflow_integration()
    
    print("\n" + "=" * 60)
    print("To run with actual LLM providers:")
    print("1. Install instructor: pip install instructor")
    print("2. Install provider SDK: pip install openai anthropic")
    print("3. Set API keys: export OPENAI_API_KEY=...")
    print("4. Run the demos!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())