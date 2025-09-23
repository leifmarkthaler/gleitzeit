"""
Validation Handler for conditional task execution.

Provides safe expression evaluation for workflow conditions,
enabling dynamic task execution based on runtime data.
"""

import asyncio
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional, Union
from simpleeval import SimpleEval, NameNotDefined
from gleitzeit.handlers.base import BaseHandler
from gleitzeit.handlers.registry import HandlerRegistry
from gleitzeit.core.models import Task, TaskResult, TaskStatus

logger = logging.getLogger(__name__)


@HandlerRegistry.register
class ValidationHandler(BaseHandler):
    """
    Handler for validation tasks that control workflow execution.
    Executes within TaskExecutionWorker like any other handler.
    """

    protocol = "validation/v1"

    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(config)
        self.evaluator = SimpleEval()

        # Add safe built-in functions
        self.evaluator.functions = {
            'len': len,
            'abs': abs,
            'min': min,
            'max': max,
            'round': round,
            'str': str,
            'int': int,
            'float': float,
            'bool': bool,
        }

    @classmethod
    def get_capabilities(cls) -> Dict[str, Any]:
        """Get handler capabilities for registration."""
        return {
            'protocol': 'validation/v1',
            'task_types': ['validation', 'condition', 'gate', 'assert'],
            'methods': {
                'validation/evaluate': {
                    'description': 'Evaluate conditions and control flow',
                    'params': {
                        'conditions': 'List of conditions to evaluate',
                        'mode': 'How to combine conditions (all/any/custom)',
                        'context': 'Additional context for evaluation',
                        'on_failure': 'What to do when validation fails (skip/fail/continue)'
                    }
                },
                'validation/assert': {
                    'description': 'Assert conditions (fail workflow if false)',
                    'params': {
                        'assertions': 'List of assertions that must be true',
                        'context': 'Additional context for evaluation'
                    }
                },
                'validation/gate': {
                    'description': 'Gate keeper for workflow branches',
                    'params': {
                        'rules': 'Gating rules with branch control',
                        'context': 'Additional context for evaluation'
                    }
                }
            }
        }

    async def execute(self, task: Task) -> TaskResult:
        """Execute validation task based on method."""
        logger.info(f"ValidationHandler executing task {task.id} with method {task.method}")

        try:
            if task.method == 'validation/evaluate':
                return await self._evaluate_conditions(task)
            elif task.method == 'validation/assert':
                return await self._assert_conditions(task)
            elif task.method == 'validation/gate':
                return await self._gate_workflow(task)
            else:
                return self.create_result(
                    task=task,
                    status=TaskStatus.FAILED,
                    error=f"Unknown validation method: {task.method}"
                )
        except Exception as e:
            logger.error(f"ValidationHandler error for task {task.id}: {e}")
            return self.create_result(
                task=task,
                status=TaskStatus.FAILED,
                error=str(e)
            )

    async def _evaluate_conditions(self, task: Task) -> TaskResult:
        """
        Evaluate conditions using safe expression evaluation.
        This runs in the TaskExecutionWorker process.
        """
        conditions = task.params.get('conditions', [])
        mode = task.params.get('mode', 'all')
        context = task.params.get('context', {})
        on_failure = task.params.get('on_failure', 'skip')

        logger.debug(f"Evaluating {len(conditions)} conditions with mode={mode}")

        # Evaluate each condition
        results = []
        details = []

        for i, condition in enumerate(conditions):
            try:
                # Handle different condition formats
                if isinstance(condition, str):
                    expression = condition
                    name = f"condition_{i+1}"
                elif isinstance(condition, dict):
                    expression = condition.get('expression', '')
                    name = condition.get('name', f"condition_{i+1}")
                else:
                    raise ValueError(f"Invalid condition format: {condition}")

                # Evaluate the expression
                result = await self._safe_evaluate(expression, context)
                results.append(result)
                details.append({
                    'name': name,
                    'expression': expression,
                    'result': result,
                    'evaluated': True
                })
                logger.debug(f"Condition '{name}': {expression} = {result}")

            except NameNotDefined as e:
                # Variable not found in context
                results.append(False)
                details.append({
                    'name': name,
                    'expression': expression,
                    'result': False,
                    'error': f"Variable not found: {e}",
                    'evaluated': False
                })
                logger.warning(f"Condition '{name}' variable not found: {e}")

            except Exception as e:
                # Other evaluation errors
                results.append(False)
                details.append({
                    'name': name,
                    'expression': expression,
                    'result': False,
                    'error': str(e),
                    'evaluated': False
                })
                logger.error(f"Condition '{name}' error: {e}")

        # Determine overall validation result
        if not results:  # No conditions provided
            valid = True
            logger.info("No conditions provided, defaulting to valid=True")
        elif mode == 'all':
            valid = all(results)
        elif mode == 'any':
            valid = any(results)
        elif mode == 'none':
            valid = not any(results)
        elif mode == 'custom':
            # Custom evaluation logic
            valid = await self._custom_evaluation(results, task.params)
        else:
            raise ValueError(f"Unknown evaluation mode: {mode}")

        # Log summary
        passed_count = sum(1 for r in results if r)
        failed_count = len(results) - passed_count
        logger.info(f"Validation result: valid={valid} ({passed_count} passed, {failed_count} failed)")

        return self.create_result(
            task=task,
            status=TaskStatus.COMPLETED,
            result={
                'valid': valid,
                'mode': mode,
                'on_failure': on_failure,
                'summary': {
                    'total': len(results),
                    'passed': passed_count,
                    'failed': failed_count
                },
                'details': details,
                'evaluated_at': datetime.utcnow().isoformat()
            }
        )

    async def _assert_conditions(self, task: Task) -> TaskResult:
        """
        Assert conditions - fail task if any assertion is false.
        Assertions are stricter than evaluations.
        """
        assertions = task.params.get('assertions', [])
        context = task.params.get('context', {})

        logger.debug(f"Asserting {len(assertions)} conditions")

        results = []
        details = []

        for i, assertion in enumerate(assertions):
            try:
                if isinstance(assertion, str):
                    expression = assertion
                    name = f"assertion_{i+1}"
                elif isinstance(assertion, dict):
                    expression = assertion.get('expression', '')
                    name = assertion.get('name', f"assertion_{i+1}")
                else:
                    raise ValueError(f"Invalid assertion format: {assertion}")

                result = await self._safe_evaluate(expression, context)
                results.append(result)

                if not result:
                    # Assertion failed
                    error_msg = f"Assertion failed: {name} - {expression}"
                    logger.error(error_msg)

                    return self.create_result(
                        task=task,
                        status=TaskStatus.FAILED,
                        error=error_msg,
                        result={
                            'valid': False,
                            'failed_assertion': name,
                            'expression': expression,
                            'all_results': details
                        }
                    )

                details.append({
                    'name': name,
                    'expression': expression,
                    'result': result,
                    'asserted': True
                })

            except Exception as e:
                error_msg = f"Assertion error in '{name}': {e}"
                logger.error(error_msg)

                return self.create_result(
                    task=task,
                    status=TaskStatus.FAILED,
                    error=error_msg,
                    result={
                        'valid': False,
                        'failed_assertion': name,
                        'expression': expression,
                        'error': str(e)
                    }
                )

        # All assertions passed
        logger.info(f"All {len(assertions)} assertions passed")

        return self.create_result(
            task=task,
            status=TaskStatus.COMPLETED,
            result={
                'valid': True,
                'assertions_passed': len(assertions),
                'details': details,
                'evaluated_at': datetime.utcnow().isoformat()
            }
        )

    async def _gate_workflow(self, task: Task) -> TaskResult:
        """
        Gate workflow execution based on rules.
        Controls which tasks should be enabled/disabled.
        """
        rules = task.params.get('rules', [])
        context = task.params.get('context', {})

        logger.debug(f"Processing {len(rules)} gating rules")

        gate_results = []
        tasks_to_skip = set()
        tasks_to_enable = set()

        for rule in rules:
            name = rule.get('name', 'unnamed_rule')
            condition = rule.get('condition')
            enable_tasks = rule.get('enable_tasks', [])
            disable_tasks = rule.get('disable_tasks', [])

            try:
                # Evaluate rule condition
                result = await self._safe_evaluate(condition, context)

                gate_results.append({
                    'name': name,
                    'condition': condition,
                    'result': result,
                    'enabled': enable_tasks if result else [],
                    'disabled': disable_tasks if result else []
                })

                if result:
                    # Rule matched - apply enables/disables
                    tasks_to_enable.update(enable_tasks)
                    tasks_to_skip.update(disable_tasks)
                    logger.info(f"Gate rule '{name}' matched: enabling {enable_tasks}, disabling {disable_tasks}")
                else:
                    # Rule didn't match - inverse logic
                    tasks_to_skip.update(enable_tasks)
                    tasks_to_enable.update(disable_tasks)

            except Exception as e:
                logger.error(f"Gate rule '{name}' error: {e}")
                gate_results.append({
                    'name': name,
                    'condition': condition,
                    'error': str(e),
                    'result': False
                })

        # Resolve conflicts (enable takes precedence)
        tasks_to_skip = tasks_to_skip - tasks_to_enable

        logger.info(f"Gate results: {len(tasks_to_enable)} tasks enabled, {len(tasks_to_skip)} tasks to skip")

        return self.create_result(
            task=task,
            status=TaskStatus.COMPLETED,
            result={
                'valid': True,
                'gate_results': gate_results,
                'control': {
                    'enable_tasks': list(tasks_to_enable),
                    'skip_tasks': list(tasks_to_skip)
                },
                'evaluated_at': datetime.utcnow().isoformat()
            }
        )

    async def _safe_evaluate(self, expression: str, context: Dict[str, Any]) -> bool:
        """
        Safely evaluate expressions without exec/eval.
        Runs in the worker process, not external.
        """
        if not expression:
            return True  # Empty expression is considered True

        # Handle None values in context
        safe_context = {}
        for key, value in context.items():
            safe_context[key] = value

        try:
            # Set context for evaluation
            self.evaluator.names = safe_context

            # Evaluate expression
            result = self.evaluator.eval(expression)

            # Convert to boolean
            return bool(result)

        except NameNotDefined:
            # Re-raise for better handling
            raise
        except Exception as e:
            logger.error(f"Expression evaluation error: {e} for expression: {expression}")
            raise

    async def _custom_evaluation(self, results: List[bool], params: Dict[str, Any]) -> bool:
        """
        Custom evaluation logic for complex conditions.
        Can be extended for specific business logic.
        """
        custom_logic = params.get('custom_logic', {})

        # Example: Minimum number of conditions must pass
        if 'min_pass' in custom_logic:
            min_pass = custom_logic['min_pass']
            passed = sum(1 for r in results if r)
            return passed >= min_pass

        # Example: Specific conditions must pass
        if 'required_indices' in custom_logic:
            required = custom_logic['required_indices']
            for idx in required:
                if idx < len(results) and not results[idx]:
                    return False
            return True

        # Default to all
        return all(results)

    async def cleanup(self):
        """Clean up handler resources."""
        logger.info("ValidationHandler cleanup completed")