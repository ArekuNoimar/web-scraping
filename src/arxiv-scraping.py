# -*- coding: utf-8 -*-
import requests
import xml.etree.ElementTree as ET
import os
from urllib.parse import quote
import time

class ArxivScraper:
    def __init__(self):
        self.base_url = "http://export.arxiv.org/api/query"
        self.download_dir = "arxiv_papers"
        
    def create_download_directory(self):
        """Create directory for downloading papers"""
        if not os.path.exists(self.download_dir):
            os.makedirs(self.download_dir)
    
    def search_papers(self, query, max_results=10):
        """Search papers using arXiv API"""
        sort_by = getattr(self, 'sort_by', 'relevance')
        sort_order = getattr(self, 'sort_order', 'descending')
        
        params = {
            'search_query': query,
            'start': 0,
            'max_results': max_results,
            'sortBy': sort_by,
            'sortOrder': sort_order
        }
        
        response = requests.get(self.base_url, params=params)
        
        if response.status_code == 200:
            return self.parse_response(response.text)
        else:
            print(f"Search error: {response.status_code}")
            return []
    
    def parse_response(self, xml_content):
        """Parse XML response and extract paper information"""
        root = ET.fromstring(xml_content)
        papers = []
        
        # Define namespaces
        ns = {
            'atom': 'http://www.w3.org/2005/Atom',
            'arxiv': 'http://arxiv.org/schemas/atom'
        }
        
        for entry in root.findall('atom:entry', ns):
            paper = {}
            
            # Title
            title_elem = entry.find('atom:title', ns)
            paper['title'] = title_elem.text.strip() if title_elem is not None else "Unknown Title"
            
            # Authors
            authors = []
            for author in entry.findall('atom:author', ns):
                name_elem = author.find('atom:name', ns)
                if name_elem is not None:
                    authors.append(name_elem.text)
            paper['authors'] = authors
            
            # Summary
            summary_elem = entry.find('atom:summary', ns)
            paper['summary'] = summary_elem.text.strip() if summary_elem is not None else ""
            
            # arXiv ID
            id_elem = entry.find('atom:id', ns)
            if id_elem is not None:
                arxiv_id = id_elem.text.split('/')[-1]
                paper['arxiv_id'] = arxiv_id
            
            # PDF link
            for link in entry.findall('atom:link', ns):
                if link.get('type') == 'application/pdf':
                    paper['pdf_url'] = link.get('href')
                    break
            
            papers.append(paper)
        
        return papers
    
    def download_paper(self, paper):
        """Download paper PDF"""
        if 'pdf_url' not in paper:
            print(f"PDF link not found: {paper['title']}")
            return False
        
        try:
            # Make filename safe
            safe_title = "".join(c for c in paper['title'] if c.isalnum() or c in (' ', '-', '_')).rstrip()
            safe_title = safe_title[:100]  # Limit filename length
            filename = f"{paper['arxiv_id']}_{safe_title}.pdf"
            filepath = os.path.join(self.download_dir, filename)
            
            print(f"Downloading: {paper['title']}")
            
            response = requests.get(paper['pdf_url'])
            if response.status_code == 200:
                with open(filepath, 'wb') as f:
                    f.write(response.content)
                print(f"Download completed: {filename}")
                return True
            else:
                print(f"Download error: {response.status_code}")
                return False
                
        except Exception as e:
            print(f"Download error: {e}")
            return False
    
    def scrape_and_download(self, query, max_results=10):
        """Search and download papers for specified query"""
        print(f"Search query: {query}")
        print(f"Max results: {max_results}")
        
        # Create download directory
        self.create_download_directory()
        
        # Search papers
        papers = self.search_papers(query, max_results)
        
        if not papers:
            print("No papers found.")
            return
        
        print(f"{len(papers)} papers found.")
        
        # Download each paper
        success_count = 0
        for i, paper in enumerate(papers, 1):
            print(f"\n[{i}/{len(papers)}]")
            print(f"Title: {paper['title']}")
            print(f"Authors: {', '.join(paper['authors'])}")
            
            if self.download_paper(paper):
                success_count += 1
            
            # Wait a bit to avoid API rate limiting
            time.sleep(1)
        
        print(f"\nCompleted: {success_count}/{len(papers)} downloads successful.")

def main():
    """Main function with command line argument support"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Download papers from arXiv based on search query",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python arxiv-scraping.py "machine learning transformer"
  python arxiv-scraping.py "deep learning" --max-results 10
  python arxiv-scraping.py "neural networks" --output-dir "my_papers"
        """
    )
    
    parser.add_argument(
        "query",
        help="Search query for arXiv papers"
    )
    
    parser.add_argument(
        "--max-results", "-n",
        type=int,
        default=10,
        help="Maximum number of papers to download (default: 10)"
    )
    
    parser.add_argument(
        "--output-dir", "-o",
        type=str,
        default="arxiv_papers",
        help="Directory to save downloaded papers (default: arxiv_papers)"
    )
    
    parser.add_argument(
        "--sort-by",
        choices=["relevance", "lastUpdatedDate", "submittedDate"],
        default="relevance",
        help="Sort order for search results (default: relevance)"
    )
    
    parser.add_argument(
        "--sort-order",
        choices=["ascending", "descending"],
        default="descending",
        help="Sort direction (default: descending)"
    )
    
    args = parser.parse_args()
    
    # Create scraper with custom output directory
    scraper = ArxivScraper()
    scraper.download_dir = args.output_dir
    
    # Update search parameters
    scraper.sort_by = args.sort_by
    scraper.sort_order = args.sort_order
    
    print(f"arXiv Paper Scraper")
    print(f"==================")
    print(f"Query: {args.query}")
    print(f"Max results: {args.max_results}")
    print(f"Output directory: {args.output_dir}")
    print(f"Sort by: {args.sort_by} ({args.sort_order})")
    print()
    
    scraper.scrape_and_download(args.query, args.max_results)

if __name__ == "__main__":
    main()