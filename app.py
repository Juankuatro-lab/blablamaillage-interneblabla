import streamlit as st
import requests
import pandas as pd
import time
import random
from bs4 import BeautifulSoup
import re
from docx import Document
from docx.shared import Inches
from docx.enum.text import WD_PARAGRAPH_ALIGNMENT
import io
import json
from typing import List, Dict, Tuple, Optional
import logging
from dataclasses import dataclass
# Imports IA - syntaxe compatible avec les dernières versions
try:
    from openai import OpenAI  # Pour OpenAI v1.0+
except ImportError:
    import openai  # Fallback pour versions antérieures
import anthropic
import google.generativeai as genai
import trafilatura
from urllib.parse import urlparse
import base64

# Configuration du logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@dataclass
class CompetitorData:
    """Structure pour stocker les données d'un concurrent"""
    url: str
    title: str
    meta_description: str
    headings: Dict[str, List[str]]
    position: int
    raw_html: str
    extraction_success: bool
    error_message: str = ""
    relevance_score: float = 0.0
    selected: bool = False

@dataclass
class SEOBrief:
    """Structure pour le brief SEO final"""
    target_keyword: str
    optimized_title: str
    optimized_meta_description: str
    headings_structure: str
    country: str
    language: str
    competitors_analyzed: List[str]

class DataForSEOConfig:
    """Configuration pour les pays et langues supportés par DataForSEO"""
    
    SUPPORTED_MARKETS = {
        "🇫🇷 France": {
            "location_code": 2250,
            "country_code": "FR",
            "languages": {"Français": "fr"},
            "google_domain": "google.fr"
        },
        "🇺🇸 États-Unis": {
            "location_code": 2840,
            "country_code": "US",
            "languages": {"English": "en"},
            "google_domain": "google.com"
        },
        "🇬🇧 Royaume-Uni": {
            "location_code": 2826,
            "country_code": "GB",
            "languages": {"English": "en"},
            "google_domain": "google.co.uk"
        },
        "🇩🇪 Allemagne": {
            "location_code": 2276,
            "country_code": "DE", 
            "languages": {"Deutsch": "de", "English": "en"},
            "google_domain": "google.de"
        },
        "🇪🇸 Espagne": {
            "location_code": 2724,
            "country_code": "ES",
            "languages": {"Español": "es", "English": "en"},
            "google_domain": "google.es"
        },
        "🇮🇹 Italie": {
            "location_code": 2380,
            "country_code": "IT",
            "languages": {"Italiano": "it", "English": "en"},
            "google_domain": "google.it"
        },
        "🇧🇪 Belgique": {
            "location_code": 2056,
            "country_code": "BE",
            "languages": {"Français": "fr", "Nederlands": "nl"},
            "google_domain": "google.be"
        },
        "🇨🇦 Canada": {
            "location_code": 2124,
            "country_code": "CA",
            "languages": {"English": "en", "Français": "fr"},
            "google_domain": "google.ca"
        }
    }
    
    @classmethod
    def get_market_config(cls, country_name: str, language_name: str) -> Dict:
        """Récupère la configuration pour un pays et une langue donnés"""
        if country_name not in cls.SUPPORTED_MARKETS:
            raise ValueError(f"Pays non supporté: {country_name}")
        
        market = cls.SUPPORTED_MARKETS[country_name]
        
        if language_name not in market["languages"]:
            raise ValueError(f"Langue non supportée pour {country_name}: {language_name}")
        
        return {
            "location_code": market["location_code"],
            "language_code": market["languages"][language_name],
            "country_code": market["country_code"],
            "google_domain": market["google_domain"]
        }
    
    @classmethod
    def get_available_languages(cls, country_name: str) -> List[str]:
        """Récupère les langues disponibles pour un pays"""
        if country_name not in cls.SUPPORTED_MARKETS:
            return []
        return list(cls.SUPPORTED_MARKETS[country_name]["languages"].keys())

class DataForSEOAPI:
    """Classe pour interfacer avec DataForSEO SERP API"""
    
    def __init__(self, username: str, password: str):
        self.username = username
        self.password = password
        self.base_url = "https://api.dataforseo.com/v3"
        self.session = requests.Session()
        
        # Configuration de l'authentification
        credentials = f"{username}:{password}"
        encoded_credentials = base64.b64encode(credentials.encode()).decode()
        self.session.headers.update({
            "Authorization": f"Basic {encoded_credentials}",
            "Content-Type": "application/json"
        })
    
    def search_serp_live(self, keyword: str, location_code: int, language_code: str, 
                        num_results: int = 10) -> List[Dict]:
        """Effectue une recherche SERP en temps réel via DataForSEO"""
        endpoint = f"{self.base_url}/serp/google/organic/live/advanced"
        
        payload = [{
            "keyword": keyword,
            "location_code": location_code,
            "language_code": language_code,
            "device": "desktop",
            "os": "windows",
            "depth": min(num_results, 100),
            "calculate_rectangles": False
        }]
        
        try:
            response = self.session.post(endpoint, json=payload)
            response.raise_for_status()
            data = response.json()
            
            if data.get("status_code") != 20000:
                logger.error(f"DataForSEO API Error: {data.get('status_message')}")
                return []
            
            # Extraction des résultats organiques
            results = []
            if data.get("tasks") and data["tasks"][0].get("result"):
                serp_items = data["tasks"][0]["result"][0].get("items", [])
                
                for i, item in enumerate(serp_items, 1):
                    if item.get("type") == "organic" and item.get("url"):
                        results.append({
                            "position": i,
                            "title": item.get("title", ""),
                            "url": item.get("url", ""),
                            "snippet": item.get("description", ""),
                            "meta_description": item.get("description", "")
                        })
                    
                    if len(results) >= num_results:
                        break
            
            return results
            
        except Exception as e:
            logger.error(f"Erreur DataForSEO API: {e}")
            return []

class TrafilaturaExtractor:
    """Classe pour extraire le contenu avec Trafilatura"""
    
    @staticmethod
    def extract_content_and_headings(url: str) -> CompetitorData:
        """Extrait le contenu et la structure Hn avec Trafilatura"""
        try:
            # Téléchargement avec trafilatura
            downloaded = trafilatura.fetch_url(url)
            
            if not downloaded:
                return CompetitorData(
                    url=url, title="", meta_description="", headings={}, 
                    position=0, raw_html="", extraction_success=False,
                    error_message="Impossible de télécharger la page"
                )
            
            # Parse HTML pour extraction manuelle des éléments
            soup = BeautifulSoup(downloaded, 'html.parser')
            
            # Extraction du title
            title_tag = soup.find('title')
            title = title_tag.get_text().strip() if title_tag else ""
            
            # Extraction meta description
            meta_desc = TrafilaturaExtractor._extract_meta_description(soup)
            
            # Extraction des headings directement depuis le HTML
            headings = TrafilaturaExtractor._extract_headings_from_html(soup)
            
            return CompetitorData(
                url=url,
                title=title,
                meta_description=meta_desc,
                headings=headings,
                position=0,  # Sera mis à jour après
                raw_html=downloaded[:1000],  # Limite pour debug
                extraction_success=True,
                error_message=""
            )
            
        except Exception as e:
            logger.error(f"Erreur Trafilatura pour {url}: {e}")
            return CompetitorData(
                url=url, title="", meta_description="", headings={}, 
                position=0, raw_html="", extraction_success=False,
                error_message=str(e)
            )
    
    @staticmethod
    def _extract_meta_description(soup: BeautifulSoup) -> str:
        """Extrait la meta description depuis le HTML"""
        # Meta description standard
        meta_desc = soup.find('meta', attrs={'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return meta_desc.get('content', '').strip()
        
        # Fallback sur property="og:description"
        og_desc = soup.find('meta', attrs={'property': 'og:description'})
        if og_desc and og_desc.get('content'):
            return og_desc.get('content', '').strip()
        
        return ""
    
    @staticmethod
    def _extract_headings_from_html(soup: BeautifulSoup) -> Dict[str, List[str]]:
        """Extrait les headings directement depuis le HTML"""
        headings = {}
        
        for level in range(1, 7):  # H1 à H6
            tag_name = f'h{level}'
            tags = soup.find_all(tag_name)
            
            if tags:
                heading_texts = []
                for tag in tags:
                    text = tag.get_text().strip()
                    if text and len(text) <= 200:  # Limite raisonnable
                        # Nettoie le texte
                        text = re.sub(r'\s+', ' ', text)
                        heading_texts.append(text)
                
                if heading_texts:
                    headings[f'H{level}'] = heading_texts
        
        return headings

class RelevanceAnalyzer:
    """Analyse la pertinence des concurrents"""
    
    @staticmethod
    def calculate_keyword_presence_score(title: str, target_keyword: str) -> float:
        """Calcule le score de présence du mot-clé dans le titre"""
        if not title or not target_keyword:
            return 0.0
        
        title_lower = title.lower()
        keyword_lower = target_keyword.lower()
        
        # Score exact match
        if keyword_lower in title_lower:
            return 1.0
        
        # Score partiel basé sur les mots individuels
        keyword_words = keyword_lower.split()
        title_words = title_lower.split()
        
        matches = sum(1 for word in keyword_words if word in title_words)
        return matches / len(keyword_words) if keyword_words else 0.0
    
    @staticmethod
    def calculate_heading_structure_score(headings: Dict[str, List[str]]) -> float:
        """Évalue la qualité de la structure des headings"""
        score = 0.0
        
        # Présence H1 (obligatoire)
        if 'H1' in headings and headings['H1']:
            score += 0.4
        
        # Présence H2 (important)
        if 'H2' in headings and len(headings['H2']) >= 2:
            score += 0.3
        
        # Diversité de la structure
        levels_present = [level for level in ['H1', 'H2', 'H3', 'H4'] if level in headings and headings[level]]
        if len(levels_present) >= 3:
            score += 0.3
        
        return min(score, 1.0)
    
    @classmethod
    def calculate_relevance_score(cls, competitor_data: CompetitorData, target_keyword: str, position: int) -> float:
        """Calcule le score de pertinence global"""
        # Score position (plus c'est haut, mieux c'est)
        position_score = max(0, (11 - position) / 10) if position <= 10 else 0
        
        # Score présence mot-clé
        keyword_score = cls.calculate_keyword_presence_score(competitor_data.title, target_keyword)
        
        # Score structure headings
        structure_score = cls.calculate_heading_structure_score(competitor_data.headings)
        
        # Score final pondéré
        final_score = (position_score * 0.4 + keyword_score * 0.4 + structure_score * 0.2)
        
        return final_score

class AIAnalyzer:
    """Classe pour interfacer avec les différentes APIs d'IA"""
    
    def __init__(self, ai_provider: str, ai_model: str, api_key: str):
        self.ai_provider = ai_provider.lower()
        self.ai_model = ai_model
        self.api_key = api_key
        
        if self.ai_provider == 'openai':
            self.openai_client = OpenAI(api_key=api_key)
        elif self.ai_provider == 'claude':
            self.anthropic_client = anthropic.Anthropic(api_key=api_key)
        elif self.ai_provider == 'gemini':
            genai.configure(api_key=api_key)
    
    @staticmethod
    def get_available_models(provider: str) -> List[Dict[str, str]]:
        """Retourne les modèles disponibles pour chaque fournisseur"""
        models = {
            'claude': [
                {
                    'model_id': 'claude-3-5-sonnet-20241022',
                    'name': 'Claude 3.5 Sonnet (Dernière version)',
                    'description': '🚀 Le plus récent et performant - Recommandé',
                    'best_for': 'Analyses SEO complexes et créativité'
                },
                {
                    'model_id': 'claude-3-opus-20240229',
                    'name': 'Claude 3 Opus',
                    'description': '💪 Le plus puissant pour analyses complexes',
                    'best_for': 'Analyses approfondies et raisonnement complexe'
                },
                {
                    'model_id': 'claude-3-sonnet-20240229',
                    'name': 'Claude 3 Sonnet',
                    'description': '⚖️ Équilibré performance/rapidité',
                    'best_for': 'Usage général équilibré'
                }
            ],
            'openai': [
                {
                    'model_id': 'gpt-4o',
                    'name': 'GPT-4o (Omni)',
                    'description': '🚀 Le plus récent et optimisé - Recommandé',
                    'best_for': 'Analyses SEO avancées avec vision multimodale'
                },
                {
                    'model_id': 'gpt-4-turbo',
                    'name': 'GPT-4 Turbo',
                    'description': '💨 Version optimisée pour la vitesse',
                    'best_for': 'Analyses rapides et efficaces'
                },
                {
                    'model_id': 'gpt-4',
                    'name': 'GPT-4',
                    'description': '🎯 Version standard puissante',
                    'best_for': 'Analyses détaillées et précises'
                }
            ],
            'gemini': [
                {
                    'model_id': 'gemini-1.5-pro',
                    'name': 'Gemini 1.5 Pro',
                    'description': '🚀 Le plus performant - Recommandé',
                    'best_for': 'Analyses SEO complexes avec large contexte'
                },
                {
                    'model_id': 'gemini-1.5-flash',
                    'name': 'Gemini 1.5 Flash',
                    'description': '⚡ Plus rapide et efficace',
                    'best_for': 'Analyses rapides avec bon rapport qualité/vitesse'
                }
            ]
        }
        return models.get(provider.lower(), [])
    
    def analyze_with_custom_prompt(self, prompt: str) -> str:
        """Effectue une analyse avec un prompt personnalisé"""
        try:
            if self.ai_provider == 'openai':
                # Nouvelle syntaxe OpenAI v1.0+
                response = self.openai_client.chat.completions.create(
                    model=self.ai_model,
                    messages=[
                        {"role": "system", "content": "Tu es un expert SEO senior."},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.3,
                    max_tokens=1500
                )
                return response.choices[0].message.content
                
            elif self.ai_provider == 'claude':
                # Syntaxe Claude (correcte)
                message = self.anthropic_client.messages.create(
                    model=self.ai_model,
                    max_tokens=1500,
                    temperature=0.3,
                    messages=[
                        {"role": "user", "content": prompt}
                    ]
                )
                return message.content[0].text
                
            elif self.ai_provider == 'gemini':
                # Syntaxe Gemini (correcte)
                model = genai.GenerativeModel(self.ai_model)
                response = model.generate_content(
                    prompt,
                    generation_config=genai.types.GenerationConfig(
                        temperature=0.3,
                        max_output_tokens=1500
                    )
                )
                return response.text
                
        except Exception as e:
            logger.error(f"Erreur API {self.ai_provider} ({self.ai_model}): {e}")
            return f"Erreur lors de l'analyse: {e}"

class PromptTemplates:
    """Templates de prompts pour les différentes analyses"""
    
    @staticmethod
    def get_structure_prompt(keyword: str, competitors_data: List[CompetitorData]) -> str:
        """Génère le prompt pour l'analyse de structure"""
        
        prompt = f"""Tu es un expert SEO.
J'ai collecté plusieurs contenus concurrents (titres, Hn, paragraphes) sur la requête "{keyword}".
Analyse-les en profondeur pour :
1. Identifier les intentions de recherche couvertes et manquantes.
2. Construire une structure Hn complète et hiérarchisée (H1, H2, H3, H4 si nécessaire).
3. Optimiser le plan pour répondre à toutes les questions des internautes et surpasser les concurrents.
4. La structure doit être claire, logique, sans répétitions inutiles, et inclure des variantes sémantiques du mot-clé.

DONNÉES DES CONCURRENTS:
"""
        
        for i, comp in enumerate(competitors_data, 1):
            if comp.extraction_success:
                prompt += f"""
CONCURRENT {i} (Position {comp.position}):
URL: {comp.url}
TITLE: {comp.title}
STRUCTURE Hn:
"""
                for level, headings in comp.headings.items():
                    for heading in headings:
                        prompt += f"  {level}: {heading}\n"
        
        prompt += """
Donne-moi uniquement :
- Un H1 optimisé (avec le mot-clé principal).
- Les H2/H3/H4 proposés sous forme d'arborescence claire.

Format de réponse attendu:
**H1:** [Ton H1 optimisé]

**H2:** [Premier H2]
* **H3:** [Premier H3]
* **H3:** [Deuxième H3]

**H2:** [Deuxième H2]
* **H3:** [Premier H3]
* **H3:** [Deuxième H3]
  * **H4:** [H4 si nécessaire]

etc.
"""
        
        return prompt
    
    @staticmethod
    def get_title_prompt(keyword: str, competitors_data: List[CompetitorData]) -> str:
        """Génère le prompt pour l'analyse de title"""
        
        prompt = f"""Tu es un expert SEO.
J'ai scrappé plusieurs titles de concurrents sur la requête "{keyword}".
Analyse-les pour :
1. Identifier leurs forces et faiblesses.
2. Créer un Title unique, différenciant, et optimisé SEO.
3. Respecter une longueur inférieure à 70 caractères.
4. Inclure le mot-clé principal sans suroptimisation, avec un ton attractif.

TITLES DES CONCURRENTS:
"""
        
        for i, comp in enumerate(competitors_data, 1):
            if comp.extraction_success and comp.title:
                prompt += f"""
Position {comp.position}: {comp.title}
URL: {comp.url}
"""
        
        prompt += """
Donne-moi uniquement :
- Une proposition de Title optimisé.

Format de réponse attendu:
**Title optimisé:** [Ton title ici]
"""
        
        return prompt
    
    @staticmethod
    def get_meta_description_prompt(keyword: str, competitors_data: List[CompetitorData]) -> str:
        """Génère le prompt pour l'analyse de meta description"""
        
        prompt = f"""Tu es un expert SEO.
J'ai scrappé plusieurs meta descriptions de concurrents sur la requête "{keyword}".
Analyse-les pour :
1. Identifier leurs forces et faiblesses.
2. Créer une Meta Description unique, différenciante, et optimisée SEO.
3. Respecter une longueur entre 140-155 caractères.
4. Inclure le mot-clé principal et un appel à l'action attractif.

META DESCRIPTIONS DES CONCURRENTS:
"""
        
        for i, comp in enumerate(competitors_data, 1):
            if comp.extraction_success and comp.meta_description:
                prompt += f"""
Position {comp.position}: {comp.meta_description}
URL: {comp.url}
"""
        
        prompt += """
Donne-moi uniquement :
- Une proposition de Meta Description optimisée.

Format de réponse attendu:
**Meta Description optimisée:** [Ta meta description ici]
"""
        
        return prompt

class WordGenerator:
    """Classe pour générer le document Word final"""
    
    @staticmethod
    def create_seo_brief_document(seo_brief: SEOBrief) -> io.BytesIO:
        """Génère le document Word du brief SEO"""
        doc = Document()
        
        # Titre principal
        title = doc.add_heading(f'Brief SEO - {seo_brief.target_keyword}', 0)
        title.alignment = WD_PARAGRAPH_ALIGNMENT.CENTER
        
        # Informations contextuelles
        context_p = doc.add_paragraph(f'Marché: {seo_brief.country} | Langue: {seo_brief.language}')
        context_p.alignment = WD_PARAGRAPH_ALIGNMENT.CENTER
        
        # Date
        date_p = doc.add_paragraph(f'Date de génération: {time.strftime("%d/%m/%Y")}')
        date_p.alignment = WD_PARAGRAPH_ALIGNMENT.CENTER
        
        doc.add_page_break()
        
        # Section SEO On-Page
        doc.add_heading('1. Optimisation On-Page', level=1)
        
        # Title
        doc.add_heading('Balise Title', level=2)
        title_p = doc.add_paragraph(seo_brief.optimized_title)
        title_p.style = 'Intense Quote'
        doc.add_paragraph(f'Caractères: {len(seo_brief.optimized_title)}')
        
        # Meta Description
        doc.add_heading('Meta Description', level=2)
        meta_p = doc.add_paragraph(seo_brief.optimized_meta_description)
        meta_p.style = 'Intense Quote'
        doc.add_paragraph(f'Caractères: {len(seo_brief.optimized_meta_description)}')
        
        # Structure Hn
        doc.add_heading('2. Structure des Headings', level=1)
        doc.add_paragraph(seo_brief.headings_structure)
        
        # Sources
        if seo_brief.competitors_analyzed:
            doc.add_heading('3. Sources Analysées', level=1)
            for i, source in enumerate(seo_brief.competitors_analyzed, 1):
                doc.add_paragraph(f'{i}. {source}')
        
        # Sauvegarde en mémoire
        buffer = io.BytesIO()
        doc.save(buffer)
        buffer.seek(0)
        
        return buffer

class SEOBriefGenerator:
    """Classe principale qui orchestre tout le processus"""
    
    def __init__(self):
        self.dataforseo_api = None
        self.extractor = TrafilaturaExtractor()
        self.analyzer = RelevanceAnalyzer()
        self.ai_analyzer = None
        
    def setup_apis(self, dataforseo_username: str, dataforseo_password: str, 
                   ai_provider: str, ai_model: str, ai_api_key: str):
        """Configure les APIs"""
        self.dataforseo_api = DataForSEOAPI(dataforseo_username, dataforseo_password)
        self.ai_analyzer = AIAnalyzer(ai_provider, ai_model, ai_api_key)
    
    def search_and_extract_competitors(self, target_keyword: str, country: str, language: str, 
                                     num_results: int = 10) -> List[CompetitorData]:
        """Recherche et extrait le contenu des concurrents"""
        if not self.dataforseo_api:
            raise ValueError("DataForSEO API non configurée")
        
        # Récupération de la configuration du marché
        market_config = DataForSEOConfig.get_market_config(country, language)
        
        # Recherche SERP via DataForSEO
        search_results = self.dataforseo_api.search_serp_live(
            target_keyword, 
            market_config["location_code"],
            market_config["language_code"],
            num_results
        )
        
        # Extraction du contenu avec Trafilatura pour chaque résultat
        competitors = []
        for result in search_results:
            competitor_data = self.extractor.extract_content_and_headings(result['url'])
            competitor_data.position = result['position']
            
            # Fallback sur les données DataForSEO si extraction échoue
            if not competitor_data.extraction_success:
                competitor_data.title = result.get('title', '')
                competitor_data.meta_description = result.get('meta_description', '')
            
            # Calcul du score de pertinence
            competitor_data.relevance_score = self.analyzer.calculate_relevance_score(
                competitor_data, target_keyword, result['position']
            )
            
            competitors.append(competitor_data)
        
        return competitors
    
    def auto_select_competitors(self, competitors: List[CompetitorData], max_competitors: int = 5) -> List[CompetitorData]:
        """Sélection automatique des meilleurs concurrents"""
        # Trie par score de pertinence
        sorted_competitors = sorted(competitors, key=lambda x: x.relevance_score, reverse=True)
        
        # Sélectionne les meilleurs
        selected = sorted_competitors[:max_competitors]
        for competitor in selected:
            competitor.selected = True
        
        return selected

# Interface Streamlit
def main():
    st.set_page_config(
        page_title="SEO Brief Generator Pro",
        page_icon="🚀",
        layout="wide"
    )
    
    st.title("🚀 Générateur de Brief SEO Professionnel")
    st.markdown("*Analyse competitive avancée avec DataForSEO + Trafilatura + IA spécialisée*")
    
    # Sidebar pour la configuration
    with st.sidebar:
        st.header("⚙️ Configuration")
        
        # APIs DataForSEO
        st.subheader("🔍 DataForSEO API")
        dataforseo_username = st.text_input("Username DataForSEO", type="password")
        dataforseo_password = st.text_input("Password DataForSEO", type="password")
        
        # Configuration IA
        st.subheader("🤖 Intelligence Artificielle")
        ai_provider = st.selectbox("Fournisseur IA", ["Claude", "OpenAI", "Gemini"])
        
        # Récupération des modèles disponibles
        available_models = AIAnalyzer.get_available_models(ai_provider.lower())
        
        if available_models:
            model_options = [f"{model['name']}" for model in available_models]
            selected_model_index = st.selectbox(
                f"Modèle {ai_provider}",
                range(len(model_options)),
                format_func=lambda x: model_options[x]
            )
            
            selected_model_info = available_models[selected_model_index]
            st.info(f"**{selected_model_info['description']}**\n\n*Idéal pour :* {selected_model_info['best_for']}")
            ai_model = selected_model_info['model_id']
        
        ai_api_key = st.text_input(f"Clé API {ai_provider}", type="password")
        
        # Mode de fonctionnement
        st.subheader("⚡ Mode de fonctionnement")
        auto_mode = st.toggle("Mode automatique", value=False, help="Exécution automatique de toutes les étapes 1-5 jusqu'au téléchargement")
        
        if not auto_mode:
            max_competitors = st.slider("Nombre max de concurrents à analyser", 3, 10, 5)
    
    # Interface principale
    col1, col2 = st.columns([2, 1])
    
    with col1:
        st.header("🎯 Configuration de recherche")
        
        # Sélection du marché
        st.subheader("🌍 Marché cible")
        countries = list(DataForSEOConfig.SUPPORTED_MARKETS.keys())
        selected_country = st.selectbox("Pays", countries)
        
        # Sélection de la langue
        available_languages = DataForSEOConfig.get_available_languages(selected_country)
        selected_language = st.selectbox("Langue", available_languages)
        
        # Mot-clé cible
        target_keyword = st.text_input("Mot-clé principal", placeholder="Exemple: comment choisir un lit coffre")
        
        num_results = st.slider("Nombre de résultats SERP à analyser", 5, 15, 10)
    
    with col2:
        if selected_country and selected_language:
            config = DataForSEOConfig.get_market_config(selected_country, selected_language)
            st.info(f"""**Configuration sélectionnée:**
📍 Pays: {selected_country}
🗣️ Langue: {selected_language}
🔗 Domaine: {config['google_domain']}""")
    
    # Initialisation du générateur
    if 'generator' not in st.session_state:
        st.session_state.generator = SEOBriefGenerator()
    
    # Validation des APIs
    apis_configured = all([dataforseo_username, dataforseo_password, ai_api_key])
    
    if not apis_configured:
        st.warning("⚠️ Veuillez configurer toutes les APIs dans la barre latérale")
        return
    
    try:
        st.session_state.generator.setup_apis(
            dataforseo_username, dataforseo_password, 
            ai_provider.lower(), ai_model, ai_api_key
        )
    except Exception as e:
        st.error(f"Erreur configuration API: {e}")
        return
    
    # Initialisation des variables de session
    if 'competitors_data' not in st.session_state:
        st.session_state.competitors_data = []
    if 'search_completed' not in st.session_state:
        st.session_state.search_completed = False
    
    # MODE AUTOMATIQUE - Exécution complète
    if auto_mode:
        if st.button("🚀 Génération automatique complète du Brief SEO", type="primary", disabled=not target_keyword):
            
            # Étape 1: Recherche et extraction
            with st.spinner("🔍 Étape 1/5 - Recherche SERP et extraction du contenu..."):
                try:
                    competitors_data = st.session_state.generator.search_and_extract_competitors(
                        target_keyword, selected_country, selected_language, num_results
                    )
                    
                    if not competitors_data:
                        st.error("❌ Aucun concurrent trouvé")
                        return
                    
                    st.session_state.competitors_data = competitors_data
                    st.session_state.search_completed = True
                    st.success(f"✅ Étape 1/5 - {len(competitors_data)} concurrents trouvés et analysés")
                    
                except Exception as e:
                    st.error(f"❌ Erreur lors de la recherche: {e}")
                    return
            
            # Étape 2: Sélection automatique
            with st.spinner("🤖 Étape 2/5 - Sélection automatique des meilleurs concurrents..."):
                selected_competitors = st.session_state.generator.auto_select_competitors(competitors_data, max_competitors=5)
                st.session_state.selected_competitors = selected_competitors
                st.success(f"✅ Étape 2/5 - {len(selected_competitors)} concurrents sélectionnés automatiquement")
            
            # Étape 3: Analyse structure
            with st.spinner("🏗️ Étape 3/5 - Analyse de la structure Hn..."):
                structure_prompt = PromptTemplates.get_structure_prompt(target_keyword, selected_competitors)
                structure_result = st.session_state.generator.ai_analyzer.analyze_with_custom_prompt(structure_prompt)
                st.session_state.structure_result = structure_result
                st.success("✅ Étape 3/5 - Analyse de structure terminée")
            
            # Étape 4: Analyse title
            with st.spinner("🏷️ Étape 4/5 - Analyse du Title..."):
                title_prompt = PromptTemplates.get_title_prompt(target_keyword, selected_competitors)
                title_result = st.session_state.generator.ai_analyzer.analyze_with_custom_prompt(title_prompt)
                st.session_state.title_result = title_result
                st.success("✅ Étape 4/5 - Analyse de title terminée")
            
            # Étape 5: Analyse meta description
            with st.spinner("📝 Étape 5/5 - Analyse de la Meta Description..."):
                meta_prompt = PromptTemplates.get_meta_description_prompt(target_keyword, selected_competitors)
                meta_result = st.session_state.generator.ai_analyzer.analyze_with_custom_prompt(meta_prompt)
                st.session_state.meta_result = meta_result
                st.success("✅ Étape 5/5 - Analyse de meta description terminée")
            
            # Génération automatique du document Word
            with st.spinner("📄 Génération du document Word..."):
                try:
                    seo_brief = SEOBrief(
                        target_keyword=target_keyword,
                        optimized_title=st.session_state.title_result,
                        optimized_meta_description=st.session_state.meta_result,
                        headings_structure=st.session_state.structure_result,
                        country=selected_country,
                        language=selected_language,
                        competitors_analyzed=[comp.url for comp in st.session_state.selected_competitors]
                    )
                    
                    word_buffer = WordGenerator.create_seo_brief_document(seo_brief)
                    
                    st.success("🎉 Génération automatique terminée avec succès !")
                    
                    st.download_button(
                        label="📄 Télécharger le Brief SEO (.docx)",
                        data=word_buffer,
                        file_name=f"brief_seo_{target_keyword.replace(' ', '_')}_{selected_country.split(' ')[1].lower()}.docx",
                        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                    )
                    
                except Exception as e:
                    st.error(f"❌ Erreur génération Word: {e}")
    
    else:
        # MODE MANUEL - Étapes séparées
        # Étape 1: Recherche et extraction des concurrents
        if st.button("🔍 1. Rechercher et extraire les concurrents", type="primary", disabled=not target_keyword):
            
            with st.spinner("🔍 Recherche SERP et extraction du contenu..."):
                try:
                    competitors_data = st.session_state.generator.search_and_extract_competitors(
                        target_keyword, selected_country, selected_language, num_results
                    )
                    
                    if not competitors_data:
                        st.error("❌ Aucun concurrent trouvé")
                        return
                    
                    st.session_state.competitors_data = competitors_data
                    st.session_state.search_completed = True
                    
                    st.success(f"✅ {len(competitors_data)} concurrents trouvés et analysés")
                    
                except Exception as e:
                    st.error(f"❌ Erreur lors de la recherche: {e}")
                    return
    
    # Affichage des données extraites (debugging)
    if st.session_state.search_completed and st.session_state.competitors_data:
        st.header("🔍 Données extraites (Debug)")
        
        competitors_data = st.session_state.competitors_data
        
        # Tableau de debug principal
        debug_data = []
        for comp in competitors_data:
            debug_data.append({
                "Position": comp.position,
                "URL": comp.url,
                "Title": comp.title[:50] + "..." if len(comp.title) > 50 else comp.title,
                "Meta Description": comp.meta_description[:50] + "..." if len(comp.meta_description) > 50 else comp.meta_description,
                "Headings trouvés": ", ".join(comp.headings.keys()) if comp.headings else "Aucun",
                "Score relevance": f"{comp.relevance_score:.2f}",
                "Extraction OK": "✅" if comp.extraction_success else "❌",
                "Erreur": comp.error_message[:30] + "..." if comp.error_message and len(comp.error_message) > 30 else comp.error_message
            })
        
        df_debug = pd.DataFrame(debug_data)
        st.dataframe(df_debug, use_container_width=True)
        
        # Nouveau tableau détaillé des structures Hn
        st.subheader("📊 Structure Hn détaillée extraite par Trafilatura")
        
        headings_data = []
        for comp in competitors_data:
            if comp.extraction_success and comp.headings:
                for level, headings_list in comp.headings.items():
                    for heading in headings_list:
                        headings_data.append({
                            "Position": comp.position,
                            "URL": comp.url[:40] + "..." if len(comp.url) > 40 else comp.url,
                            "Level": level,
                            "Heading": heading,
                            "Caractères": len(heading)
                        })
        
        if headings_data:
            df_headings = pd.DataFrame(headings_data)
            # Tri par position puis par level
            df_headings = df_headings.sort_values(['Position', 'Level'])
            st.dataframe(df_headings, use_container_width=True)
        else:
            st.warning("⚠️ Aucune structure Hn extraite par Trafilatura")
        
        # Sélection des concurrents à analyser (MODE MANUEL uniquement)
        if not auto_mode:
            st.subheader("📋 Sélection manuelle des concurrents à analyser")
            
            if 'selected_competitors' not in st.session_state:
                st.session_state.selected_competitors = []
            
            selected_indices = st.multiselect(
                "Choisissez les concurrents à inclure dans l'analyse",
                range(len(competitors_data)),
                format_func=lambda x: f"#{competitors_data[x].position} - {competitors_data[x].title[:60]}... (Score: {competitors_data[x].relevance_score:.2f})",
                default=list(range(min(5, len(competitors_data))))  # Sélectionne les 5 premiers par défaut
            )
            
            st.session_state.selected_competitors = [competitors_data[i] for i in selected_indices]
        
        # Continuer avec les analyses si des concurrents sont sélectionnés (MODE MANUEL)
        if not auto_mode and st.session_state.get('selected_competitors') and len(st.session_state.selected_competitors) > 0:
            st.success(f"✅ {len(st.session_state.selected_competitors)} concurrents sélectionnés pour l'analyse")
            
            # Étape 2: Analyse de la structure Hn
            st.header("🏗️ 2. Analyse de la structure Hn")
            
            # Génération du prompt pour la structure
            structure_prompt = PromptTemplates.get_structure_prompt(target_keyword, st.session_state.selected_competitors)
            
            # Zone de texte modifiable pour le prompt
            custom_structure_prompt = st.text_area(
                "Prompt pour l'analyse de structure (modifiable)",
                value=structure_prompt,
                height=200,
                key="structure_prompt"
            )
            
            if st.button("🚀 Analyser la structure Hn"):
                with st.spinner("Analyse de la structure en cours..."):
                    structure_result = st.session_state.generator.ai_analyzer.analyze_with_custom_prompt(custom_structure_prompt)
                    st.session_state.structure_result = structure_result
                    st.success("✅ Analyse de structure terminée")
            
            # Affichage du résultat structure
            if 'structure_result' in st.session_state:
                st.subheader("📊 Structure Hn optimisée")
                st.markdown(st.session_state.structure_result)
            
            # Étape 3: Analyse du Title
            st.header("🏷️ 3. Analyse du Title")
            
            # Génération du prompt pour le title
            title_prompt = PromptTemplates.get_title_prompt(target_keyword, st.session_state.selected_competitors)
            
            custom_title_prompt = st.text_area(
                "Prompt pour l'analyse du title (modifiable)",
                value=title_prompt,
                height=200,
                key="title_prompt"
            )
            
            if st.button("🚀 Analyser le Title"):
                with st.spinner("Analyse du title en cours..."):
                    title_result = st.session_state.generator.ai_analyzer.analyze_with_custom_prompt(custom_title_prompt)
                    st.session_state.title_result = title_result
                    st.success("✅ Analyse de title terminée")
            
            # Affichage du résultat title
            if 'title_result' in st.session_state:
                st.subheader("🏷️ Title optimisé")
                st.markdown(st.session_state.title_result)
            
            # Étape 4: Analyse de la Meta Description
            st.header("📝 4. Analyse de la Meta Description")
            
            # Génération du prompt pour la meta description
            meta_prompt = PromptTemplates.get_meta_description_prompt(target_keyword, st.session_state.selected_competitors)
            
            custom_meta_prompt = st.text_area(
                "Prompt pour l'analyse de la meta description (modifiable)",
                value=meta_prompt,
                height=200,
                key="meta_prompt"
            )
            
            if st.button("🚀 Analyser la Meta Description"):
                with st.spinner("Analyse de la meta description en cours..."):
                    meta_result = st.session_state.generator.ai_analyzer.analyze_with_custom_prompt(custom_meta_prompt)
                    st.session_state.meta_result = meta_result
                    st.success("✅ Analyse de meta description terminée")
            
            # Affichage du résultat meta description
            if 'meta_result' in st.session_state:
                st.subheader("📝 Meta Description optimisée")
                st.markdown(st.session_state.meta_result)
            
            # Génération du brief final
            if all(key in st.session_state for key in ['structure_result', 'title_result', 'meta_result']):
                st.header("📄 5. Brief SEO Final")
                
                # Aperçu du brief
                col1, col2 = st.columns(2)
                
                with col1:
                    st.subheader("🏷️ Balises SEO")
                    st.write("**Title:**")
                    st.code(st.session_state.title_result)
                    
                    st.write("**Meta Description:**")
                    st.code(st.session_state.meta_result)
                
                with col2:
                    st.subheader("📊 Structure Hn")
                    st.markdown(st.session_state.structure_result)
                
                if st.button("📄 Générer le document Word"):
                    try:
                        seo_brief = SEOBrief(
                            target_keyword=target_keyword,
                            optimized_title=st.session_state.title_result,
                            optimized_meta_description=st.session_state.meta_result,
                            headings_structure=st.session_state.structure_result,
                            country=selected_country,
                            language=selected_language,
                            competitors_analyzed=[comp.url for comp in st.session_state.selected_competitors]
                        )
                        
                        word_buffer = WordGenerator.create_seo_brief_document(seo_brief)
                        
                        st.download_button(
                            label="📄 Télécharger le Brief SEO (.docx)",
                            data=word_buffer,
                            file_name=f"brief_seo_{target_keyword.replace(' ', '_')}_{selected_country.split(' ')[1].lower()}.docx",
                            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                        )
                        
                        st.success("✅ Document Word généré!")
                        
                    except Exception as e:
                        st.error(f"❌ Erreur génération Word: {e}")
        
        elif not auto_mode:
            st.warning("⚠️ Veuillez sélectionner au moins un concurrent pour continuer")
    
    # Affichage des résultats si mode automatique et analyses terminées
    if auto_mode and all(key in st.session_state for key in ['structure_result', 'title_result', 'meta_result']):
        st.header("📄 Brief SEO Généré Automatiquement")
        
        # Aperçu du brief
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("🏷️ Balises SEO")
            st.write("**Title:**")
            st.code(st.session_state.title_result)
            
            st.write("**Meta Description:**")
            st.code(st.session_state.meta_result)
        
        with col2:
            st.subheader("📊 Structure Hn")
            st.markdown(st.session_state.structure_result)
    
    # Bouton pour reset
    if st.session_state.search_completed:
        if st.button("🔄 Nouvelle recherche"):
            # Reset de toutes les variables de session
            for key in ['competitors_data', 'search_completed', 'selected_competitors', 'structure_result', 'title_result', 'meta_result']:
                if key in st.session_state:
                    del st.session_state[key]
            st.rerun()

if __name__ == "__main__":
    main()
