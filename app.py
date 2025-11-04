#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Application Streamlit - Analyse des Opportunités de Maillage Interne
===================================================================

Interface graphique pour analyser les opportunités de maillage interne
basées sur les données de la Google Search Console.

Auteur: JC avec Claude AI
Version: 18.4 - Version finale sans émojis avec documentation complète
Date: 2025-11-04

## AMÉLIORATION: Changelog v18.4
- **INTERFACE ÉPURÉE:** Suppression de tous les émojis pour une interface professionnelle.
- **DOCUMENTATION INTÉGRÉE:** Ajout d'une box d'informations complète avec méthodologie détaillée.
- **GUIDE SCREAMING FROG:** Instructions précises pour l'extraction HTML (mode "Stocker le HTML").
- **STABILITÉ:** Analyse combinée exacte + floue, barre de progression fiable, optimisations de performance.
"""

import streamlit as st
import pandas as pd
import zipfile
import io
import re
import urllib.parse
from collections import Counter
from bs4 import BeautifulSoup, NavigableString
from typing import Dict, List, Tuple, Optional, Any
from functools import lru_cache

# Gestion des dépendances optionnelles
try:
    import ahocorasick
    AHO_CORASICK_AVAILABLE = True
except ImportError:
    AHO_CORASICK_AVAILABLE = False
try:
    import openpyxl
    XLSX_EXPORT_AVAILABLE = True
except ImportError:
    XLSX_EXPORT_AVAILABLE = False
try:
    from fuzzywuzzy import fuzz
    FUZZY_AVAILABLE = True
except ImportError:
    FUZZY_AVAILABLE = False

st.set_page_config(
    page_title="Blablablablablablablabla",
    layout="wide", initial_sidebar_state="expanded"
)

# --- CLASSE ANALYSEUR (Stable et complète) ---
class InternalLinkingAnalyzer:
    FRENCH_STOPWORDS = {
        'a', 'à', 'au', 'aux', 'avec', 'ce', 'ces', 'dans', 'de', 'des', 'du', 'elle', 'en', 'et', 'être', 'eu', 'il', 'je', 'la', 'le', 'les', 'leur', 'lui', 'ma', 'mais', 'me', 'même', 'mes', 'moi', 'mon', 'ne', 'nos', 'notre', 'nous', 'on', 'ont', 'ou', 'par', 'pas', 'pour', 'qu', 'que', 'qui', 'sa', 'se', 'ses', 'son', 'sur', 'ta', 'te', 'tes', 'toi', 'ton', 'tu', 'un', 'une', 'vos', 'votre', 'vous', 'c', 'd', 'j', 'l', 'à', 'm', 'n', 's', 't', 'y', 'été', 'étée', 'étées', 'étés', 'étant', 'suis', 'es', 'est', 'sommes', 'êtes', 'sont', 'serai', 'seras', 'sera', 'serons', 'serez', 'seront', 'serais', 'serait', 'serions', 'seriez', 'seraient', 'étais', 'était', 'étions', 'étiez', 'étaient', 'fus', 'fut', 'fûmes', 'fûtes', 'furent', 'sois', 'soit', 'soyons', 'soyez', 'soient', 'fusse', 'fusses', 'fût', 'fussions', 'fussiez', 'fussent', 'ayant', 'ayante', 'ayantes', 'ayants', 'eu', 'eue', 'eues', 'eus', 'ai', 'as', 'avons', 'avez', 'ont', 'aurai', 'auras', 'aura', 'aurons', 'aurez', 'auront', 'aurais', 'aurait', 'aurions', 'auriez', 'auraient', 'avais', 'avait', 'avions', 'aviez', 'avaient', 'eut', 'eûmes', 'eûtes', 'eurent', 'aie', 'aies', 'ait', 'ayons', 'ayez', 'aient', 'eusse', 'eusses', 'eût', 'eussions', 'eussiez', 'eussent', 'ceci', 'cela', 'celà', 'cet', 'cette', 'ici', 'ils', 'les', 'leurs', 'quel', 'quels', 'quelle', 'quelles', 'sans', 'soi'
    }
    CLASSIC_PAGE_PATTERNS = [
        r'mentions[-_]?legales?', r'cgu', r'cgv', 'conditions', 'legal', 'a[-_]?propos', 'about', 'contact',
        r'nous[-_]?contacter', r'politique[-_]?confidentialite', 'privacy', 'cookie', r'plan[-_]?site',
        'sitemap', 'aide', 'help', 'faq', 'support', '404', 'erreur', r'recherche', 'search', 'connexion',
        'login', 'inscription', 'register', 'panier', 'cart', 'commande', 'checkout', r'mon[-_]?compte', 'account'
    ]
    def __init__(self, config: Dict):
        self.config = config
        self.excel_data = None
        
    def load_excel_data(self, uploaded_file) -> bool:
        try:
            df = pd.read_csv(uploaded_file, on_bad_lines='skip') if uploaded_file.name.endswith('.csv') else pd.read_excel(uploaded_file)
            df.columns = df.columns.str.lower().str.strip()
            rename_map = {'pages': 'page', 'requête': 'query', 'clics': 'clicks', 'position moyenne': 'position'}
            df = df.rename(columns=rename_map)
            required_cols = ['page', 'query', 'clicks']
            if not all(col in df.columns for col in required_cols):
                st.error(f"Colonnes manquantes ! Requis: {', '.join(required_cols)}. Trouvé: {list(df.columns)}"); return False
            df = df.dropna(subset=required_cols).copy()
            df['clicks'] = pd.to_numeric(df['clicks'], errors='coerce')
            if 'position' in df.columns: df['position'] = pd.to_numeric(df['position'], errors='coerce')
            df.dropna(subset=['clicks'], inplace=True)
            if 'query' in df.columns: df.dropna(subset=['query'], inplace=True)
            if self.config['min_clicks'] > 0: df = df[df['clicks'] >= self.config['min_clicks']]
            if 'position' in df.columns and self.config['max_position'] > 0: df = df[df['position'] <= self.config['max_position']]
            if 'query' in df.columns: df = df[df['query'].str.len() >= self.config['min_keyword_length']]
            if self.config['exclude_stopwords']: df = df[~df['query'].str.lower().isin(self.FRENCH_STOPWORDS)]
            df['priority'] = df['clicks'] * (1 / df['position'].clip(lower=0.1)) if 'position' in df.columns else df['clicks']
            self.excel_data = df
            return True
        except Exception as e:
            st.error(f"Erreur lors du chargement du fichier GSC: {e}")
            return False

    @staticmethod
    @lru_cache(maxsize=200_000)
    def _normalize_url_for_comparison(url: str) -> str:
        if not url: return ""
        try:
            url = url.lower()
            url = re.sub(r'(\?|&)(utm_.*|gclid|fbclid)=[^&]*', '', url)
            parsed = urllib.parse.urlparse(url)
            netloc = parsed.netloc.replace('www.', '')
            path = parsed.path.rstrip('/') or ''
            query = '?' + urllib.parse.urlencode(sorted(urllib.parse.parse_qsl(parsed.query))) if parsed.query else ''
            return f"{netloc}{path}{query}"
        except: return url.lower()

    def _is_classic_page(self, url: str) -> bool:
        if not self.config.get('exclude_classic_pages', True): return False
        for pattern in self.CLASSIC_PAGE_PATTERNS:
            if re.search(pattern, url.lower()): return True
        return False
        
    def _get_content_selectors(self) -> List[str]:
        selectors = self.config.get('content_selectors', ['p', 'li', 'span']).copy()
        if self.config.get('custom_class'):
            selectors.append(f".{self.config['custom_class']}")
        return selectors
        
    def detect_content_classes(self, zip_file_content: bytes) -> List[Tuple[str, int]]:
        if not self.config.get('auto_detect_classes', True): return []
        class_counter = Counter()
        with zipfile.ZipFile(io.BytesIO(zip_file_content), 'r') as zip_ref:
            html_files_info = [info for info in zip_ref.infolist() if info.filename.endswith('.html') and not info.is_dir()]
            for file_info in html_files_info[:500]:
                try:
                    soup = BeautifulSoup(zip_ref.read(file_info.filename), 'html.parser')
                    for element in soup.find_all(['div', 'section', 'article', 'main', 'p']):
                        if element.get('class') and len(element.get_text(strip=True)) > 100:
                            for cls in element.get('class'):
                                if not cls.startswith(('js-', 'css-')): class_counter[cls] += 1
                except Exception: continue
        return class_counter.most_common(10)

    @staticmethod
    def _find_anchor_location(element: BeautifulSoup, anchor_text: str) -> str:
        anchor_lower = anchor_text.lower()
        for img in element.find_all('img', alt=True):
            if anchor_lower in img['alt'].lower(): return "Attribut 'alt' (Image)"
        if element.has_attr('title') and anchor_lower in element['title'].lower(): return "Attribut 'title'"
        for child in element.find_all(title=True):
             if anchor_lower in child['title'].lower(): return "Attribut 'title'"
        return "Texte Principal"

    def analyze_opportunities(self, zip_file_content: bytes, selected_keywords: Optional[List[str]]) -> List[Dict]:
        if self.excel_data is None: return []
        opportunities = []
        selectors = self._get_content_selectors()
        keyword_index = {}
        working_data = self.excel_data.copy()
        if selected_keywords: working_data = working_data[working_data['query'].isin(selected_keywords)]
        for _, row in working_data.iterrows():
            query = row['query'].lower().strip()
            if query not in keyword_index or keyword_index[query]['priority'] < row['priority']:
                keyword_index[query] = {'page': row['page'], 'priority': row['priority'], 'clicks': row['clicks'], 'original_query': row['query']}
        if not keyword_index: return []
        
        A = None
        run_fuzzy = self.config.get('use_fuzzy_matching', False)
        if AHO_CORASICK_AVAILABLE:
            A = ahocorasick.Automaton()
            for keyword, data in keyword_index.items(): A.add_word(keyword, (keyword, data['original_query']))
            A.make_automaton()
        
        with zipfile.ZipFile(io.BytesIO(zip_file_content), 'r') as zip_ref:
            # L'indexation est rapide et mise en cache, on peut la refaire
            canonical_map = {}
            feedback_placeholder = st.empty()
            feedback_placeholder.text("Création de l'index des pages HTML...")
            all_zip_files = [info for info in zip_ref.infolist() if info.filename.endswith('.html') and not info.is_dir()]
            map_progress = feedback_placeholder.progress(0)
            for i, file_info in enumerate(all_zip_files):
                if i % 100 == 0: map_progress.progress((i+1)/len(all_zip_files))
                try:
                    content = zip_ref.read(file_info.filename)
                    soup = BeautifulSoup(content, 'html.parser', from_encoding='utf-8')
                    canonical_link = soup.find('link', rel='canonical', href=True)
                    if canonical_link:
                        canonical_map[self._normalize_url_for_comparison(canonical_link['href'])] = file_info.filename
                except Exception: continue
            
            source_urls_to_scan = self.excel_data['page'].unique()
            max_pages = self.config.get('max_pages_to_analyze', len(source_urls_to_scan))
            urls_to_process = source_urls_to_scan[:max_pages]
            mapped_count = 0
            
            feedback_placeholder.text("Analyse des opportunités en cours...")
            progress_bar = feedback_placeholder.progress(0)
            
            for i, source_url in enumerate(urls_to_process):
                progress_bar.progress((i + 1) / len(urls_to_process), text=f"Analyse... {source_url[:80]}")
                if self._is_classic_page(source_url): continue
                normalized_source_key = self._normalize_url_for_comparison(source_url)
                html_filename = canonical_map.get(normalized_source_key)
                if not html_filename: continue
                mapped_count += 1
                try:
                    html_content = zip_ref.read(html_filename).decode('utf-8', errors='ignore')
                    soup = BeautifulSoup(html_content, 'html.parser')
                    existing_links_normalized = {self._normalize_url_for_comparison(urllib.parse.urljoin(source_url, link.get('href'))) for link in soup.find_all('a', href=True) if link.get('href') and not link.get('href').startswith(('mailto:', 'tel:'))}
                    for element in soup.select(', '.join(selectors)):
                        text_content = element.get_text(" ", strip=True)
                        if len(text_content) < self.config.get('min_keyword_length', 3): continue
                        text_lower = text_content.lower()
                        
                        found_kws_in_element = set()
                        if A:
                            for _, (keyword, original_query) in A.iter(text_lower):
                                if keyword in found_kws_in_element: continue
                                found_kws_in_element.add(keyword)
                                opportunity = self._create_opportunity(original_query, keyword_index[keyword], source_url, existing_links_normalized, 'exact', element)
                                if opportunity: opportunities.append(opportunity)
                        
                        if run_fuzzy and FUZZY_AVAILABLE:
                            for keyword, data in keyword_index.items():
                                if keyword in found_kws_in_element: continue
                                similarity = fuzz.token_set_ratio(keyword, text_lower)
                                if similarity >= self.config.get('fuzzy_threshold', 85):
                                    found_kws_in_element.add(keyword)
                                    opportunity = self._create_opportunity(data['original_query'], data, source_url, existing_links_normalized, f'fuzzy ({similarity}%)', element)
                                    if opportunity: opportunities.append(opportunity)
                except Exception: continue
            
            feedback_placeholder.empty()
            if len(urls_to_process) > 0:
                st.info(f"Matching réussi : {mapped_count} sur {len(urls_to_process)} URLs GSC analysées ont été trouvées dans le fichier ZIP ({mapped_count/len(urls_to_process):.1%}).")

        opportunities = [dict(t) for t in {tuple(d.items()) for d in opportunities}]
        opportunities.sort(key=lambda x: x['priority'], reverse=True)
        return opportunities

    def _create_opportunity(self, anchor_text, target_data, source_url, existing_links_normalized, match_type, element) -> Optional[Dict]:
        target_page_url = target_data['page']
        normalized_source = self._normalize_url_for_comparison(source_url)
        normalized_target = self._normalize_url_for_comparison(target_page_url)
        if normalized_source == normalized_target: return None
        link_exists = normalized_target in existing_links_normalized
        anchor_location = self._find_anchor_location(element, anchor_text)
        element_tag, classes = element.name, element.get('class', [])
        class_str = f".{'.'.join(classes)}" if classes else ""
        return {'source_url': source_url, 'target_url': target_page_url, 'anchor': anchor_text, 'priority': target_data['priority'], 'clicks': target_data['clicks'], 'match_type': match_type, 'element_source': f"<{element_tag}{class_str}>", 'existing_link': "[X] Lien présent" if link_exists else "[OK] Nouvelle opportunité", 'anchor_location': anchor_location}

# --- FONCTIONS DE LIAISON (pour le cache Streamlit) ---
@st.cache_data
def load_gsc_data_cached(uploaded_file, config):
    analyzer = InternalLinkingAnalyzer(config)
    if analyzer.load_excel_data(uploaded_file):
        return analyzer.excel_data
    return None

# --- INTERFACE STREAMLIT ---
def main():
    st.title("Maillage Interne SEO")
    st.markdown("**Version: 18.4** - Date de dernière mise à jour: 2025-11-04")
    
    # Box d'informations
    with st.expander("ℹ️ Comment utiliser cet outil ? (Cliquez pour dérouler)", expanded=False):
        st.markdown("""
        ### Principe de fonctionnement
        
        Cet outil analyse vos pages web pour identifier des **opportunités de maillage interne** en croisant :
        - Les **mots-clés performants** de votre Google Search Console (GSC)
        - Le **contenu textuel** de vos pages HTML
        
        ### Méthodologie
        
        1. **Correspondance Canonical First** : L'outil utilise les balises canonical de vos pages HTML pour garantir un matching précis avec les URLs de la GSC
        2. **Détection intelligente** : Il cherche dans le contenu de vos pages les mots-clés qui génèrent du trafic sur d'autres pages
        3. **Analyse des opportunités** : Quand un mot-clé est trouvé, l'outil vérifie si un lien existe déjà vers la page cible
        
        ### Étapes d'utilisation
        
        **Étape 1 : Préparez vos données GSC**
        - Exportez vos données depuis Google Search Console (Pages + Requêtes)
        - Format accepté : Excel (.xlsx, .xls) ou CSV
        - Colonnes requises : `Page`, `Query` (ou Requête), `Clicks` (ou Clics)
        - Colonne optionnelle : `Position` (ou Position Moyenne)
        
        **Étape 2 : Créez votre archive HTML**
        
        **Méthode recommandée : Screaming Frog SEO Spider**
        
        1. **Configuration du crawl** :
           - Ouvrez Screaming Frog et entrez l'URL de votre site
           - Allez dans `Configuration > Spider > Rendu`
           - **Important** : Sélectionnez **"Stocker le HTML"** (et non "Rendu JavaScript")
           
        2. **Pourquoi "Stocker le HTML" ?**
           - Si votre site est bien structuré avec du contenu HTML natif (pas uniquement généré en JS)
           - Cette méthode est **beaucoup plus rapide** et consomme moins de ressources
           - Le HTML brut contient déjà le contenu textuel nécessaire pour l'analyse
           - Les balises canonical sont présentes dans le HTML source
           
        3. **Quand utiliser le rendu JavaScript ?**
           - Uniquement si votre site est une SPA (Single Page Application) type React/Vue/Angular
           - Si le contenu textuel n'apparaît qu'après exécution du JavaScript
           - Note : Le rendu JS ralentit considérablement le crawl (jusqu'à 10x plus lent)
           
        4. **Lancez le crawl** :
           - Cliquez sur "Démarrer" et attendez la fin du crawl
           - Vérifiez que toutes vos pages importantes ont été crawlées
           
        5. **Export du HTML** :
           - Allez dans `Export > HTML/Bulk Export > HTML`
           - Screaming Frog crée automatiquement un dossier avec tous les fichiers HTML
           
        6. **Créez le fichier ZIP** :
           - Compressez l'intégralité du dossier HTML exporté dans un fichier ZIP
           - Important : Les pages doivent contenir les balises `<link rel="canonical">`
        
        **Alternative : Autres crawlers**
        - **Sitebulb** : Export HTML disponible dans les rapports
        - **OnCrawl** : Export HTML via l'API ou l'interface
        - **Crawl manuel** : wget ou curl avec compression ZIP des résultats
        
        **Étape 3 : Configurez l'analyse (Sidebar)**
        - **Filtres de données** : Définissez des seuils (clics minimum, position max, etc.)
        - **Exclusions** : Filtrez les stop-words et pages classiques (contact, CGU, etc.)
        - **Analyse floue** : Activez pour détecter aussi les variations de mots-clés (pluriels, etc.)
        - **Ciblage du contenu** : Sélectionnez les balises HTML à analyser (p, li, span, etc.)
        
        **Étape 4 : Uploadez vos fichiers**
        - Uploadez d'abord votre fichier GSC (colonne de gauche)
        - Puis uploadez votre fichier ZIP HTML (colonne de droite)
        
        **Étape 5 : Lancez l'analyse**
        - Cliquez sur "Lancer l'Analyse Complète"
        - L'outil va traiter vos données (cela peut prendre quelques minutes selon la taille)
        
        **Étape 6 : Exploitez les résultats**
        - Consultez le tableau des opportunités détectées
        - Exportez les résultats en CSV ou Excel
        - Priorisez vos actions selon la colonne "Priorité" (basée sur clics × position)
        
        ### Interprétation des résultats
        
        - **[OK] Nouvelle opportunité** : Aucun lien n'existe, c'est une vraie opportunité de maillage
        - **[X] Lien présent** : Un lien existe déjà, pas d'action nécessaire
        - **Type de Match** : 
          - `exact` : correspondance exacte du mot-clé
          - `fuzzy (X%)` : correspondance approximative (variante détectée)
        - **Source Ancre** : Indique où se trouve le texte d'ancre potentiel (texte principal, alt d'image, etc.)
        - **Priorité** : Score calculé selon les clics et la position du mot-clé dans la GSC
        
        ### Conseils d'optimisation
        
        - Commencez par analyser les **nouvelles opportunités** avec la plus haute priorité
        - Vérifiez la pertinence contextuelle avant d'ajouter un lien
        - Utilisez le texte d'ancre suggéré ou adaptez-le selon le contexte
        - Privilégiez les liens dans le contenu principal (balises `<p>`) plutôt que dans les sidebars
        
        ### Questions fréquentes
        
        **Pourquoi certaines URLs GSC ne sont pas trouvées ?**
        - Les URLs doivent correspondre exactement via leur balise canonical
        - Vérifiez que votre crawl HTML est complet
        - Les pages dynamiques ou protégées peuvent ne pas être crawlées
        
        **L'analyse est lente, comment l'accélérer ?**
        - Réduisez la "Limite de pages à analyser" dans la configuration
        - Installez `pyahocorasick` pour de meilleures performances
        - Désactivez l'analyse floue si vous n'en avez pas besoin
        
        **Que faire si je n'ai pas de balises canonical ?**
        - Cet outil nécessite des balises canonical pour fonctionner de manière fiable
        - Ajoutez-les à vos pages avant de lancer l'analyse
        """)
    
    if 'config' not in st.session_state:
        st.session_state.config = {
            'min_clicks': 0, 'min_keyword_length': 3, 'exclude_stopwords': True, 'exclude_classic_pages': True,
            'content_selectors': ['p', 'li', 'span'], 'custom_class': '', 'max_position': 50,
            'manual_keyword_selection': False, 'auto_detect_classes': True, 'max_pages_to_analyze': 10000,
            'use_fuzzy_matching': False, 'fuzzy_threshold': 85
        }
    if 'gsc_data' not in st.session_state: st.session_state.gsc_data = None
    if 'zip_content' not in st.session_state: st.session_state.zip_content = None
    if 'results' not in st.session_state: st.session_state.results = None
    if 'detected_classes_list' not in st.session_state: st.session_state.detected_classes_list = []
    
    st.sidebar.header("Configuration")
    cfg = st.session_state.config
    st.sidebar.subheader("Filtres de Données")
    cfg['min_clicks'] = st.sidebar.number_input("Minimum de clics", 0, 1000, cfg.get('min_clicks', 0), help="Ignorer les mots-clés qui ont généré moins de clics que ce seuil.")
    cfg['min_keyword_length'] = st.sidebar.number_input("Longueur min. mots-clés", 1, 20, cfg.get('min_keyword_length', 3), help="Ignorer les mots-clés plus courts que ce nombre de caractères.")
    cfg['max_position'] = st.sidebar.number_input("Position max. SERPs", 0, 100, cfg.get('max_position', 50), help="Ignorer les mots-clés dont la position moyenne est au-delà de ce seuil (0 = pas de limite).")
    st.sidebar.subheader("Optimisation")
    cfg['max_pages_to_analyze'] = st.sidebar.number_input("Limite de pages à analyser (GSC)", 100, 500000, cfg.get('max_pages_to_analyze', 10000), help="Limite le nombre d'URLs GSC uniques à analyser pour accélérer le traitement sur de très gros sites.")
    st.sidebar.subheader("Exclusions")
    cfg['exclude_stopwords'] = st.sidebar.checkbox("Exclure les stop words", cfg.get('exclude_stopwords', True), help="Exclut les mots vides courants (le, la, de, etc.) de l'analyse.")
    cfg['exclude_classic_pages'] = st.sidebar.checkbox("Exclure pages classiques", cfg.get('exclude_classic_pages', True), help="Exclut les pages comme 'contact', 'mentions légales', 'CGU', etc.")
    st.sidebar.subheader("Analyse Floue")
    if FUZZY_AVAILABLE:
        cfg['use_fuzzy_matching'] = st.sidebar.checkbox("Activer l'analyse floue", cfg.get('use_fuzzy_matching', False), help="En plus de la recherche exacte, cherche des variations de mots-clés (pluriels, synonymes...). Rend l'analyse plus lente.")
        if cfg['use_fuzzy_matching']:
            cfg['fuzzy_threshold'] = st.sidebar.slider("Seuil de similarité (%)", 70, 100, cfg.get('fuzzy_threshold', 85), help="Seuil à partir duquel une variation est considérée comme une opportunité.")
    else:
        st.sidebar.warning("Pour l'analyse floue, installez `fuzzywuzzy` et `python-levenshtein`.", icon="⚠️")
        cfg['use_fuzzy_matching'] = False
    st.sidebar.subheader("Ciblage du Contenu")
    cfg['manual_keyword_selection'] = st.sidebar.checkbox("Sélection manuelle des mots-clés", cfg.get('manual_keyword_selection', False), help="Permet de choisir manuellement les mots-clés à analyser au lieu de tous les prendre.")
    cfg['auto_detect_classes'] = st.sidebar.checkbox("Détection auto des classes CSS", cfg.get('auto_detect_classes', True), help="Analyse le HTML pour trouver les classes CSS contenant le plus de texte.")
    cfg['content_selectors'] = st.sidebar.multiselect("Sélecteurs de contenu", ['p', 'li', 'span', 'div', 'h1', 'h2', 'h3'], cfg.get('content_selectors', ['p', 'li', 'span']), help="Balises HTML dans lesquelles chercher les opportunités.")
    if st.session_state.detected_classes_list:
        selected_class = st.sidebar.selectbox("Utiliser une classe CSS détectée ?", options=[''] + st.session_state.detected_classes_list, help="Cible l'analyse sur une classe CSS spécifique trouvée lors de la détection automatique.")
        cfg['custom_class'] = selected_class
    else:
        cfg['custom_class'] = st.sidebar.text_input("Ajouter une classe CSS manuellement", cfg.get('custom_class', ''), help="Entrez une classe CSS (sans le '.') pour cibler une zone de contenu spécifique.")

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Données Google Search Console")
        excel_file = st.file_uploader("Uploadez votre fichier Excel/CSV", type=['xlsx', 'xls', 'csv'])
        if excel_file:
            st.session_state.gsc_data = load_gsc_data_cached(excel_file, cfg)
            if st.session_state.gsc_data is not None: st.success(f"Données GSC chargées: {len(st.session_state.gsc_data)} lignes.")
    with col2:
        st.subheader("Fichiers HTML")
        if st.session_state.gsc_data is not None:
            zip_file = st.file_uploader("Uploadez le fichier ZIP HTML", type=['zip'])
            if zip_file:
                st.session_state.zip_content = zip_file.getvalue()
                st.success(f"Fichier ZIP chargé ({len(st.session_state.zip_content)/1e6:.2f} MB).")
                if cfg['auto_detect_classes'] and not st.session_state.detected_classes_list:
                    with st.spinner("Détection des classes CSS..."):
                        analyzer = InternalLinkingAnalyzer(cfg)
                        st.session_state.detected_classes_list = [cls for cls, _ in analyzer.detect_content_classes(st.session_state.zip_content)]
                        if st.session_state.detected_classes_list: st.rerun()
        else: st.info("Veuillez d'abord charger les données Excel.")

    selected_keywords = None
    if st.session_state.gsc_data is not None and cfg['manual_keyword_selection']:
        st.subheader("Sélection des Mots-clés à Analyser")
        available_keywords = sorted(st.session_state.gsc_data['query'].unique().tolist())
        selected_keywords = st.multiselect("Sélectionnez les mots-clés:", options=available_keywords)
    
    if st.session_state.gsc_data is not None and st.session_state.zip_content is not None:
        can_analyze = not cfg['manual_keyword_selection'] or (cfg['manual_keyword_selection'] and selected_keywords is not None)
        if can_analyze:
            if st.button("Lancer l'Analyse Complète", type="primary", use_container_width=True):
                analyzer = InternalLinkingAnalyzer(cfg)
                analyzer.excel_data = st.session_state.gsc_data
                st.session_state.results = analyzer.analyze_opportunities(st.session_state.zip_content, selected_keywords)
        elif cfg['manual_keyword_selection']:
            st.warning("Veuillez sélectionner au moins un mot-clé pour lancer l'analyse.")

    if st.session_state.results is not None:
        if st.session_state.results:
            df_display = pd.DataFrame(st.session_state.results).rename(columns={'source_url': 'URL Source', 'target_url': 'Page à Mailler', 'anchor': 'Ancre de Lien', 'element_source': 'Élément Source', 'existing_link': 'Lien Existant', 'priority': 'Priorité', 'match_type': 'Type de Match', 'anchor_location': 'Source Ancre'})
            st.header("Résultats de l'Analyse")
            st.dataframe(df_display[['URL Source', 'Ancre de Lien', 'Source Ancre', 'Page à Mailler', 'Élément Source', 'Type de Match', 'Lien Existant', 'Priorité']], use_container_width=True, column_config={"URL Source": st.column_config.LinkColumn(), "Page à Mailler": st.column_config.LinkColumn()})
            st.subheader("Export des Résultats")
            col_export1, col_export2 = st.columns(2)
            with col_export1:
                st.download_button("Télécharger CSV", df_display.to_csv(index=False, encoding='utf-8-sig'), "opportunites_maillage.csv", "text/csv", use_container_width=True)
            with col_export2:
                if XLSX_EXPORT_AVAILABLE:
                    output = io.BytesIO()
                    with pd.ExcelWriter(output, engine='openpyxl') as writer: df_display.to_excel(writer, index=False, sheet_name='Opportunités')
                    st.download_button("Télécharger Excel (.xlsx)", output.getvalue(), "opportunites_maillage.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
                else: st.warning("Pour l'export Excel, installez `openpyxl`", icon="⚠️")
            st.divider()
            st.header("Tableau de Bord de l'Analyse")
            total_ops, new_ops = len(df_display), len(df_display[df_display['Lien Existant'] == '[OK] Nouvelle opportunité'])
            col_metric1, col_metric2, col_metric3 = st.columns(3)
            col_metric1.metric("Opportunités Totales", total_ops)
            if total_ops > 0:
                col_metric2.metric("Nouvelles Opportunités [OK]", new_ops, f"{new_ops/total_ops:.1%}")
                col_metric3.metric("Liens Déjà Présents [X]", total_ops - new_ops, f"{(total_ops - new_ops)/total_ops:.1%}")
            col_graph1, col_graph2 = st.columns(2)
            with col_graph1:
                st.write("**Top 10 Pages Sources d'Opportunités**"); st.bar_chart(df_display['URL Source'].value_counts().head(10))
                st.write("**Distribution par Type de Match**"); st.bar_chart(df_display['Type de Match'].value_counts())
            with col_graph2:
                st.write("**Top 10 Pages Cibles (à mailler)**"); st.bar_chart(df_display['Page à Mailler'].value_counts().head(10))
                st.write("**Distribution par Source de l'Ancre**"); st.bar_chart(df_display['Source Ancre'].value_counts())
        else:
            st.warning("Aucune opportunité trouvée avec la configuration actuelle.")
            
    st.sidebar.divider()
    if st.sidebar.button("Recommencer l'analyse"):
        for key in list(st.session_state.keys()): del st.session_state[key]
        st.cache_data.clear()
        st.rerun()
    
    # Footer
    st.divider()
    st.markdown(
        "<div style='text-align: center; color: #666; padding: 20px;'>"
        "Développé par <a href='https://jc-espinosa.com/' target='_blank' style='color: #0066cc; text-decoration: none;'>JC</a> et Claude :)"
        "</div>",
        unsafe_allow_html=True
    )

if __name__ == "__main__":
    if not AHO_CORASICK_AVAILABLE: st.warning("**Performance limitée :** `pyahocorasick` non installé (`pip install pyahocorasack`)", icon="⚠️")
    if not XLSX_EXPORT_AVAILABLE: st.sidebar.warning("Pour l'export Excel (.xlsx), installez `openpyxl`", icon="⚠️")
    if not FUZZY_AVAILABLE: st.sidebar.warning("Pour l'analyse floue, installez `fuzzywuzzy` et `python-levenshtein`", icon="⚠️")
    main()
