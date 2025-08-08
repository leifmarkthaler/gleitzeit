# Gleitzeit Examples

Working examples that demonstrate the current API and capabilities.

## ✅ Working Examples (Current API)

### Basic Examples
- **`simple_example.py`** - Basic text generation and function calls
- **`functions_demo.py`** - Built-in function capabilities  
- **`workflow_demo.py`** - Multi-step workflows with dependencies
- **`vision_demo.py`** - Image analysis (requires Ollama + llava)

### Requirements
- **Ollama** (for LLM tasks): `curl -fsSL https://ollama.ai/install.sh | sh`
- **Models**: `ollama pull llama3` and `ollama pull llava` (for vision)

## Running Examples

```bash
# Basic functionality
python examples/simple_example.py

# Explore built-in functions
python examples/functions_demo.py

# Multi-step workflows
python examples/workflow_demo.py

# Vision analysis (requires images)
python examples/vision_demo.py
```

## Example Features Demonstrated

### ✅ Current API Features
- **Task Types**: TEXT, VISION, FUNCTION, HTTP, FILE
- **Workflow Dependencies**: Using `{{task_id.result}}` syntax
- **Function Registry**: 30+ built-in secure functions
- **Async Support**: Both sync and async functions
- **Error Handling**: Graceful failure management
- **Real-time Monitoring**: Workflow progress tracking

### 🔧 Built-in Functions Shown
- **Math**: `fibonacci_sequence`, `factorial`
- **Text**: `count_words`, `extract_keywords`
- **Data**: `analyze_numbers`, `random_data`, `aggregate`
- **Async**: `async_timer`, `async_batch_process`

## ❌ Deprecated Examples

The following examples use old APIs and need updates:
- `minimal_example.py` - Old TaskType names and methods
- `workflow_examples.py` - Deprecated workflow API
- `secure_python_demo.py` - Old parameter format
- `full_cluster_demo.py` - Old NodeCapabilities API

## Creating Test Images

For vision examples, create test images:

```bash
# Download a sample image
curl -o test_image.jpg "https://picsum.photos/800/600"

# Or use any JPG/PNG file you have
cp your_image.jpg test_image.jpg
```

## Next Steps

1. Start with `simple_example.py` to verify your setup
2. Explore functions with `functions_demo.py`  
3. Build workflows with `workflow_demo.py`
4. Try vision tasks with `vision_demo.py` (after setting up Ollama + llava)

## CLI Equivalents

Most examples can also be run via CLI:

```bash
# Function call
gleitzeit run --function fibonacci_sequence --args n=10

# Text generation  
gleitzeit run --text "Write a short story about AI"

# Vision analysis
gleitzeit run --vision test_image.jpg --prompt "Describe this image"

# Workflow from file
gleitzeit run --workflow example_workflow.yaml
```