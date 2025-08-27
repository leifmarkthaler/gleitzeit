"""
Batch processing operations mixin for Gleitzeit client.
"""

from typing import Any, Dict, List, Optional
import os
from pathlib import Path


class BatchProcessingMixin:
    """Mixin providing batch processing operations."""
    
    async def batch_process(self, 
                          directory: str,
                          pattern: str = "*",
                          method: str = "llm/chat",
                          prompt: str = None,
                          model: str = "llama3.2:latest",
                          max_concurrent: int = 5,
                          name: Optional[str] = None) -> Dict[str, Any]:
        """
        Process multiple files in batch.
        
        Args:
            directory: Directory containing files to process
            pattern: File pattern (glob syntax)
            method: Processing method to use
            prompt: Prompt template for processing
            model: Model to use for processing
            max_concurrent: Maximum concurrent operations
            name: Batch job name
            
        Returns:
            Batch processing results
        """
        if not self._adapter:
            raise RuntimeError("Client not initialized")
            
        return await self._adapter.batch_process(
            directory=directory,
            pattern=pattern,
            method=method,
            prompt=prompt,
            model=model,
            max_concurrent=max_concurrent,
            name=name
        )
    
    async def process_directory(self,
                              directory: str,
                              file_extensions: List[str],
                              workflow_yaml: str,
                              max_concurrent: int = 5,
                              recursive: bool = True) -> Dict[str, Any]:
        """
        Process all files in a directory with specified extensions using a workflow template.
        
        Args:
            directory: Directory path to process
            file_extensions: List of file extensions to process
            workflow_yaml: Workflow template with placeholders
            max_concurrent: Maximum concurrent workflows
            recursive: Whether to search subdirectories
            
        Returns:
            Dictionary with processing results
        """
        if not self._adapter:
            raise RuntimeError("Client not initialized")
            
        return await self._adapter.process_directory(
            directory=directory,
            file_extensions=file_extensions,
            workflow_yaml=workflow_yaml,
            max_concurrent=max_concurrent,
            recursive=recursive
        )
    
    async def batch_process_with_progress(self,
                                        directory: str,
                                        pattern: str = "*",
                                        method: str = "llm/chat",
                                        prompt: str = None,
                                        model: str = "llama3.2:latest",
                                        max_concurrent: int = 5):
        """
        Process files in batch with progress updates.
        
        Yields progress updates as files are processed.
        
        Args:
            directory: Directory to process
            pattern: File pattern
            method: Processing method
            prompt: Prompt template
            model: Model to use
            max_concurrent: Maximum concurrent operations
            
        Yields:
            Progress updates with completed/total counts
        """
        # Find matching files
        from glob import glob
        import asyncio
        
        dir_path = Path(directory)
        if pattern.startswith("**/"):
            files = list(dir_path.rglob(pattern[3:]))
        else:
            files = list(dir_path.glob(pattern))
        
        total = len(files)
        completed = 0
        
        # Process files with concurrency limit
        semaphore = asyncio.Semaphore(max_concurrent)
        
        async def process_file(file_path):
            nonlocal completed
            async with semaphore:
                # Create task for file
                task = {
                    "method": method,
                    "input": {
                        "file": str(file_path),
                        "prompt": prompt,
                        "model": model
                    }
                }
                
                result = await self.execute_task(task)
                completed += 1
                
                # Yield progress
                return {
                    "file": str(file_path),
                    "result": result,
                    "progress": {
                        "completed": completed,
                        "total": total,
                        "percentage": (completed / total) * 100
                    }
                }
        
        # Process all files
        tasks = [process_file(f) for f in files]
        
        for coro in asyncio.as_completed(tasks):
            result = await coro
            yield result
    
    async def batch_analyze_files(self,
                                 files: List[str],
                                 analysis_prompt: str,
                                 model: str = "llama3.2:latest",
                                 output_format: str = "json") -> Dict[str, Any]:
        """
        Analyze multiple files with a common prompt.
        
        Args:
            files: List of file paths
            analysis_prompt: Analysis prompt template
            model: Model to use
            output_format: Output format (json, text, markdown)
            
        Returns:
            Analysis results for each file
        """
        import asyncio
        
        results = {}
        
        async def analyze_file(file_path):
            # Read file content
            with open(file_path, 'r') as f:
                content = f.read()
            
            # Create analysis task
            task = {
                "method": "llm/chat",
                "input": {
                    "prompt": analysis_prompt.replace("{content}", content)
                                           .replace("{filename}", Path(file_path).name),
                    "model": model,
                    "format": output_format
                }
            }
            
            return await self.execute_task(task)
        
        # Analyze all files concurrently
        analyses = await asyncio.gather(
            *[analyze_file(f) for f in files],
            return_exceptions=True
        )
        
        # Map results to files
        for file_path, analysis in zip(files, analyses):
            if not isinstance(analysis, Exception):
                results[file_path] = analysis
            else:
                results[file_path] = {"error": str(analysis)}
        
        return results
    
    async def batch_transform_files(self,
                                  input_dir: str,
                                  output_dir: str,
                                  pattern: str,
                                  transformation: str,
                                  model: str = "llama3.2:latest") -> Dict[str, Any]:
        """
        Transform files from input directory to output directory.
        
        Args:
            input_dir: Input directory
            output_dir: Output directory
            pattern: File pattern to match
            transformation: Transformation prompt
            model: Model to use
            
        Returns:
            Transformation results
        """
        # Create output directory if needed
        os.makedirs(output_dir, exist_ok=True)
        
        # Process files
        result = await self.batch_process(
            directory=input_dir,
            pattern=pattern,
            method="llm/transform",
            prompt=transformation,
            model=model
        )
        
        # Save transformed files
        for file_path, content in result.items():
            output_path = Path(output_dir) / Path(file_path).name
            with open(output_path, 'w') as f:
                f.write(content)
        
        return {
            "processed": len(result),
            "output_directory": output_dir,
            "files": list(result.keys())
        }