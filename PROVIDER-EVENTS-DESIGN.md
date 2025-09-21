# Provider Events Design

## The Challenge

For event listeners like `on("llm.token_limit_exceeded")` to work, providers need to emit events during execution.

## Solution: Event-Aware Providers

### Option 1: Provider Event Context (Simple)

```python
# In provider implementation
class LLMProvider:
    async def generate(self, prompt: str, context: EventContext):
        """Provider can emit events through context"""
        
        # Emit start event
        await context.emit("llm.started", {"prompt_length": len(prompt)})
        
        try:
            # Check token limit
            token_count = self.count_tokens(prompt)
            if token_count > self.max_tokens:
                # Emit custom event
                await context.emit("llm.token_limit_exceeded", {
                    "tokens": token_count,
                    "limit": self.max_tokens
                })
                # Could switch model here or let listener handle it
                
            # Stream tokens
            async for token in self.stream_tokens(prompt):
                await context.emit("llm.token", {"token": token})
                
            await context.emit("llm.completed", {"total_tokens": token_count})
            
        except RateLimitError as e:
            await context.emit("llm.rate_limited", {"retry_after": e.retry_after})
            raise
```

### Option 2: Provider Decorators

```python
from gleitzeit.providers import provider, emits

@provider("llm/v1")
class LLMProvider:
    
    @emits("llm.token_limit_exceeded", "llm.rate_limited")
    async def generate(self, prompt: str):
        token_count = self.count_tokens(prompt)
        
        if token_count > self.max_tokens:
            # Decorator handles event emission
            self.emit("llm.token_limit_exceeded", {
                "tokens": token_count,
                "limit": self.max_tokens
            })
            # Optionally continue with fallback
            return await self.generate_with_fallback(prompt)
        
        return await self._generate(prompt)
    
    @emits("llm.model_switched")
    async def generate_with_fallback(self, prompt: str):
        self.emit("llm.model_switched", {
            "from": self.model,
            "to": self.fallback_model
        })
        # Use fallback model
        return await self._generate(prompt, model=self.fallback_model)
```

### Option 3: Event Hooks in Provider Base

```python
class BaseProvider:
    """Enhanced base provider with event support"""
    
    def __init__(self):
        self.event_handlers = {}
        self._event_bus = None  # Injected by system
    
    async def emit(self, event: str, data: dict = None):
        """Emit event to system"""
        if self._event_bus:
            await self._event_bus.emit(f"{self.protocol}.{event}", {
                "task_id": self.current_task_id,
                "provider": self.protocol,
                "event": event,
                "data": data,
                "timestamp": datetime.utcnow()
            })
    
    def on(self, event: str, handler):
        """Register internal event handler"""
        self.event_handlers[event] = handler
        return self

# Usage in provider
class PaymentProvider(BaseProvider):
    protocol = "payment/v1"
    
    async def charge(self, amount: float, card: str):
        await self.emit("charge.started", {"amount": amount})
        
        try:
            result = await self._process_payment(amount, card)
            
            if result.requires_3ds:
                await self.emit("3ds.required", {"url": result.verification_url})
                
            if result.declined:
                await self.emit("payment.declined", {
                    "reason": result.decline_reason,
                    "code": result.decline_code
                })
                
            await self.emit("charge.completed", {"success": result.success})
            return result
            
        except PaymentGatewayError as e:
            await self.emit("gateway.error", {"error": str(e)})
            raise
```

## Standard Provider Events

### Common Events All Providers Could Emit

```python
STANDARD_EVENTS = {
    # Lifecycle
    "*.started": "Task execution started",
    "*.completed": "Task execution completed",
    "*.failed": "Task execution failed",
    
    # Performance
    "*.slow": "Task taking longer than expected",
    "*.timeout": "Task timed out",
    
    # Retries
    "*.retry": "Task being retried",
    "*.retry_exhausted": "All retries failed",
    
    # Resources
    "*.rate_limited": "Hit rate limit",
    "*.quota_exceeded": "Exceeded quota",
    "*.resource_unavailable": "Required resource not available"
}
```

### Protocol-Specific Events

```python
LLM_EVENTS = {
    "llm.token": "Single token generated",
    "llm.chunk": "Chunk of text generated",
    "llm.token_limit_exceeded": "Prompt too long",
    "llm.content_filtered": "Content filter triggered",
    "llm.model_switched": "Switched to different model",
    "llm.hallucination_detected": "Potential hallucination",
}

PAYMENT_EVENTS = {
    "payment.3ds_required": "3D Secure verification needed",
    "payment.declined": "Payment declined",
    "payment.fraud_detected": "Potential fraud",
    "payment.refund_initiated": "Refund started",
}

API_EVENTS = {
    "api.rate_limited": "Hit API rate limit",
    "api.authentication_failed": "Auth failed",
    "api.endpoint_deprecated": "Using deprecated endpoint",
    "api.response_malformed": "Invalid response format",
}
```

## Workflow Integration

```python
from gleitzeit.easy import t, w, on

workflow = w(
    t("generate_content", "llm/v1:generate")
        .with_(prompt="${input.prompt}", model="gpt-4"),
    
    # Provider-emitted event handlers
    on("llm.token_limit_exceeded")
        .run("switch_to_smaller_model", "llm/v1:generate")
        .with_(prompt="${input.prompt}", model="gpt-3.5-turbo"),
    
    on("llm.rate_limited")
        .run("wait_and_retry", "timer/v1:wait")
        .with_(seconds="${event.retry_after}")
        .then("generate_content"),  # Retry original task
    
    on("llm.content_filtered")
        .run("log_filtered_content", "audit/v1:log")
        .with_(reason="${event.filter_reason}")
        .run("use_safe_prompt", "llm/v1:generate")
        .with_(prompt="${input.safe_prompt}"),
    
    on("payment.3ds_required")
        .run("send_verification_link", "email/v1:send")
        .with_(url="${event.verification_url}"),
    
    on("payment.declined")
        .run("try_alternate_payment", "payment/v1:charge")
        .with_(method="${customer.backup_payment}")
)
```

## Implementation in Executor

```python
class TaskExecutor:
    async def execute_task(self, task: Task, context: Dict):
        """Execute task with event support"""
        
        # Create event context for provider
        event_context = EventContext(
            task_id=task.id,
            workflow_id=task.workflow_id,
            event_bus=self.event_bus
        )
        
        # Get provider
        provider = self.get_provider(task.protocol)
        
        # Inject event context
        if hasattr(provider, 'set_event_context'):
            provider.set_event_context(event_context)
        
        # Execute with event monitoring
        try:
            await self.event_bus.emit(f"{task.protocol}.started", {
                "task_id": task.id,
                "params": task.params
            })
            
            result = await provider.execute(task.method, task.params)
            
            await self.event_bus.emit(f"{task.protocol}.completed", {
                "task_id": task.id,
                "result": result
            })
            
            return result
            
        except Exception as e:
            await self.event_bus.emit(f"{task.protocol}.failed", {
                "task_id": task.id,
                "error": str(e)
            })
            raise
```

## Real Example: LLM Provider with Events

```python
class OpenAIProvider(BaseProvider):
    protocol = "llm/v1"
    
    async def generate(self, prompt: str, model: str = "gpt-4", **kwargs):
        # Check token limit
        token_count = self.count_tokens(prompt)
        
        if token_count > self.get_model_limit(model):
            # Emit event - workflow can react
            await self.emit("token_limit_exceeded", {
                "tokens": token_count,
                "limit": self.get_model_limit(model),
                "model": model
            })
            
            # Provider could handle internally or let workflow handle
            if self.auto_fallback:
                model = self.get_smaller_model(model)
                await self.emit("model_switched", {
                    "from": kwargs.get("model"),
                    "to": model,
                    "reason": "token_limit"
                })
        
        # Make API call
        try:
            response = await self.client.completions.create(
                prompt=prompt,
                model=model,
                stream=True
            )
            
            # Stream response with events
            result = ""
            async for chunk in response:
                token = chunk.choices[0].delta.content
                if token:
                    await self.emit("token", {"token": token})
                    result += token
            
            # Check for potential issues
            if self.detect_hallucination(result):
                await self.emit("hallucination_detected", {
                    "confidence": self.hallucination_confidence,
                    "result": result
                })
            
            return result
            
        except RateLimitError as e:
            await self.emit("rate_limited", {
                "retry_after": e.retry_after,
                "model": model
            })
            raise
        
        except ContentFilterError as e:
            await self.emit("content_filtered", {
                "filter_reason": e.reason,
                "categories": e.categories
            })
            raise
```

## Benefits

1. **Decoupling** - Workflows don't need to know provider internals
2. **Flexibility** - Providers can emit domain-specific events
3. **Reusability** - Same event handlers across workflows
4. **Observability** - Rich event stream for monitoring
5. **Extensibility** - Add new events without changing workflow

## Migration Path

### Phase 1: Add event context to base provider
```python
class BaseProvider:
    async def emit(self, event: str, data: dict = None):
        # Just log initially
        logger.info(f"Event: {event}", extra=data)
```

### Phase 2: Wire up to event bus
```python
# Connect to Redis Streams
await self.event_bus.publish(event, data)
```

### Phase 3: Provider-specific events
```python
# Each provider adds domain events
await self.emit("llm.hallucination_detected", {...})
```

This gives providers the ability to emit rich events that workflows can react to, enabling sophisticated event-driven patterns!