#!/usr/bin/env python3
"""
Analyze batch processing results
"""

# Access the batch results from the previous task
batch_results = context.get('summarize_documents', {}).get('result', {})

if batch_results:
    total_docs = len(batch_results)
    topics = []
    
    # Extract topics from each document summary
    for file_path, result in batch_results.items():
        if result.get('status') == 'success':
            content = result.get('content', '')
            # Simple topic extraction (in real use, this would be more sophisticated)
            if 'automation' in content.lower():
                topics.append('automation')
            if 'meeting' in content.lower():
                topics.append('meeting')
            if 'technical' in content.lower() or 'specification' in content.lower():
                topics.append('technical')
            if 'story' in content.lower() or 'narrative' in content.lower():
                topics.append('narrative')
    
    # Count unique topics
    unique_topics = list(set(topics))
    
    result = {
        'total_documents': total_docs,
        'unique_topics': unique_topics,
        'topic_count': len(unique_topics),
        'most_common': max(set(topics), key=topics.count) if topics else None
    }
    
    print(f"Analyzed {total_docs} documents")
    print(f"Found {len(unique_topics)} unique topics: {', '.join(unique_topics)}")
    if result['most_common']:
        print(f"Most common topic: {result['most_common']}")
else:
    result = {
        'error': 'No batch results found',
        'total_documents': 0
    }
    print("No batch results to analyze")