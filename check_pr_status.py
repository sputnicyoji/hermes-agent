#!/usr/bin/env python3
import os
import requests
import json
import sys

# GitHub token - try environment first, then .env file
token = os.environ.get('GITHUB_TOKEN')
if not token:
    try:
        with open(os.path.expanduser('~/.hermes/.env'), 'r') as f:
            for line in f:
                if line.startswith('GITHUB_TOKEN='):
                    token = line.split('=', 1)[1].strip()
                    break
    except:
        pass

if not token:
    print("No GitHub token found")
    sys.exit(1)

headers = {
    'Authorization': f'token {token}',
    'Accept': 'application/vnd.github.v3+json'
}

pr_numbers = [8954, 8957, 8960, 8988]
repo = 'NousResearch/hermes-agent'

results = {}

for pr_num in pr_numbers:
    try:
        # Get PR basic info
        pr_url = f'https://api.github.com/repos/{repo}/pulls/{pr_num}'
        pr_response = requests.get(pr_url, headers=headers, timeout=30)
        
        if pr_response.status_code == 200:
            pr_data = pr_response.json()
            
            # Get reviews
            reviews_url = f'{pr_url}/reviews'
            reviews_response = requests.get(reviews_url, headers=headers, timeout=30)
            reviews = reviews_response.json() if reviews_response.status_code == 200 else []
            
            # Get status checks
            status_url = f'https://api.github.com/repos/{repo}/commits/{pr_data["head"]["sha"]}/status'
            status_response = requests.get(status_url, headers=headers, timeout=30)
            status_data = status_response.json() if status_response.status_code == 200 else {}
            
            # Get comments
            comments_url = f'{pr_url}/comments'
            comments_response = requests.get(comments_url, headers=headers, timeout=30)
            comments = comments_response.json() if comments_response.status_code == 200 else []
            
            # Get review comments
            review_comments_url = f'{pr_url}/review_comments'
            review_comments_response = requests.get(review_comments_url, headers=headers, timeout=30)
            review_comments = review_comments_response.json() if review_comments_response.status_code == 200 else []
            
            results[pr_num] = {
                'state': pr_data['state'],
                'title': pr_data['title'],
                'merged': pr_data.get('merged', False),
                'review_count': len(reviews),
                'latest_review': reviews[0] if reviews else None,
                'status_checks': status_data.get('state', 'unknown'),
                'status_details': status_data.get('statuses', []),
                'comments_count': len(comments),
                'review_comments_count': len(review_comments),
                'labels': [label['name'] for label in pr_data.get('labels', [])],
                'milestone': pr_data.get('milestone', {}).get('title') if pr_data.get('milestone') else None,
                'created_at': pr_data['created_at'],
                'updated_at': pr_data['updated_at'],
                'user': pr_data['user']['login']
            }
        else:
            results[pr_num] = {'error': f'Status {pr_response.status_code}'}
    except Exception as e:
        results[pr_num] = {'error': str(e)}

print(json.dumps(results, indent=2))
