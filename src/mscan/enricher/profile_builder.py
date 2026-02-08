"""Profile builder for creating enriched brand profiles.

Combines mscan website scan data with SEC EDGAR enrichment to build
comprehensive brand profiles with marketing insights and recommendations.
"""

import logging
from typing import Optional, List, Dict, Any
from datetime import datetime

from mscan.models.enriched_brand import (
    EnrichedBrand,
    SECProfile,
    FinancialMetrics,
    EnrichmentResult,
)

logger = logging.getLogger(__name__)


class ProfileBuilderError(Exception):
    """Base exception for profile builder errors."""
    pass


class ProfileBuilder:
    """Builds enriched brand profiles from mscan and SEC data.
    
    Combines website scanning results with SEC EDGAR financial data
    to create comprehensive marketing profiles with insights and
    qualification scores.
    
    Args:
        min_revenue_threshold: Minimum annual revenue to qualify (USD).
        min_employee_threshold: Minimum employee count to qualify.
        
    Example:
        >>> builder = ProfileBuilder()
        >>> brand = builder.build_profile(
        ...     domain="apple.com",
        ...     scan_data={"technologies": [...]},
        ...     sec_profile=sec_profile
        ... )
    """
    
    # Revenue tiers for qualification scoring
    REVENUE_TIERS = [
        (1_000_000_000_000, 100),  # $1T+ → 100 points
        (100_000_000_000, 90),     # $100B+ → 90 points
        (10_000_000_000, 80),      # $10B+ → 80 points
        (1_000_000_000, 70),       # $1B+ → 70 points
        (500_000_000, 60),         # $500M+ → 60 points
        (100_000_000, 50),         # $100M+ → 50 points
        (10_000_000, 40),          # $10M+ → 40 points
        (1_000_000, 30),           # $1M+ → 30 points
    ]
    
    # Employee count tiers
    EMPLOYEE_TIERS = [
        (100_000, 25),   # 100K+ → 25 points
        (10_000, 20),    # 10K+ → 20 points
        (1_000, 15),     # 1K+ → 15 points
        (100, 10),       # 100+ → 10 points
    ]
    
    # Marketing spend tiers (as % of revenue)
    MARKETING_SPEND_TIERS = [
        (0.20, 20),  # 20%+ of revenue → 20 points
        (0.10, 15),  # 10%+ → 15 points
        (0.05, 10),  # 5%+ → 10 points
        (0.02, 5),   # 2%+ → 5 points
    ]
    
    def __init__(
        self,
        min_revenue_threshold: int = 0,
        min_employee_threshold: int = 0
    ):
        self.min_revenue_threshold = min_revenue_threshold
        self.min_employee_threshold = min_employee_threshold
    
    def build_profile(
        self,
        domain: str,
        scan_data: Optional[Dict[str, Any]] = None,
        sec_profile: Optional[SECProfile] = None,
        enrichment_result: Optional[EnrichmentResult] = None
    ) -> EnrichedBrand:
        """Build a complete enriched brand profile.
        
        Args:
            domain: Website domain.
            scan_data: Optional mscan website scan data.
            sec_profile: Optional SEC profile from EDGAR client.
            enrichment_result: Optional enrichment result with metadata.
            
        Returns:
            Complete EnrichedBrand profile.
        """
        scan_data = scan_data or {}
        
        # Extract detected technologies from scan data
        detected_technologies = scan_data.get('detected_technologies', [])
        if not detected_technologies and 'vendors' in scan_data:
            # Convert from scan format
            detected_technologies = [
                {'vendor': v.get('vendor_name', 'Unknown'), 
                 'category': v.get('category', 'Unknown')}
                for v in scan_data.get('vendors', [])
            ]
        
        # Build the enriched brand
        brand = EnrichedBrand(
            domain=domain,
            scanned_at=scan_data.get('scanned_at') or datetime.now(),
            detected_technologies=detected_technologies,
            sec_profile=sec_profile,
            is_publicly_traded=sec_profile is not None,
            confidence_level="high" if sec_profile else "low",
            data_completeness=self._calculate_data_completeness(
                scan_data, sec_profile
            )
        )
        
        # Calculate qualification score
        brand.qualification_score = self._calculate_qualification_score(
            sec_profile, detected_technologies
        )
        
        # Generate insights and recommendations
        brand.insights = self._generate_insights(brand, sec_profile)
        brand.recommendations = self._generate_recommendations(brand, sec_profile)
        
        # Update confidence based on data quality
        brand.confidence_level = self._determine_confidence_level(brand)
        
        logger.info(f"Built profile for {domain}: score={brand.qualification_score}, "
                   f"confidence={brand.confidence_level}")
        
        return brand
    
    def _calculate_data_completeness(
        self,
        scan_data: Dict[str, Any],
        sec_profile: Optional[SECProfile]
    ) -> float:
        """Calculate data completeness ratio (0.0-1.0)."""
        total_fields = 0
        filled_fields = 0
        
        # Check scan data
        if scan_data:
            total_fields += 3
            if scan_data.get('detected_technologies') or scan_data.get('vendors'):
                filled_fields += 1
            if scan_data.get('requests'):
                filled_fields += 1
            if scan_data.get('scanned_at'):
                filled_fields += 1
        
        # Check SEC profile
        if sec_profile:
            total_fields += 6
            if sec_profile.company_name:
                filled_fields += 1
            if sec_profile.sic_code:
                filled_fields += 1
            if sec_profile.exchange:
                filled_fields += 1
            if sec_profile.latest_financials:
                filled_fields += 1
            if sec_profile.filings_metadata:
                filled_fields += 1
            if sec_profile.entity_metadata:
                filled_fields += 1
        else:
            total_fields += 1  # Missing SEC data
        
        return filled_fields / total_fields if total_fields > 0 else 0.0
    
    def _calculate_qualification_score(
        self,
        sec_profile: Optional[SECProfile],
        detected_technologies: List[Dict[str, Any]]
    ) -> int:
        """Calculate marketing qualification score (0-100)."""
        score = 0
        max_score = 100
        
        if not sec_profile or not sec_profile.latest_financials:
            # Base score on tech stack sophistication only
            return min(len(detected_technologies) * 5, 40)
        
        financials = sec_profile.latest_financials
        
        # Revenue score (up to 40 points)
        if financials.revenue_usd:
            for threshold, points in self.REVENUE_TIERS:
                if financials.revenue_usd >= threshold:
                    score += points
                    break
        
        # Employee count score (up to 25 points)
        if financials.employee_count:
            for threshold, points in self.EMPLOYEE_TIERS:
                if financials.employee_count >= threshold:
                    score += points
                    break
        
        # Marketing spend score (up to 20 points)
        if financials.marketing_spend_usd and financials.revenue_usd:
            spend_ratio = financials.marketing_spend_usd / financials.revenue_usd
            for threshold, points in self.MARKETING_SPEND_TIERS:
                if spend_ratio >= threshold:
                    score += points
                    break
        
        # R&D investment score (up to 15 points)
        if financials.rd_spend_usd and financials.revenue_usd:
            rd_ratio = financials.rd_spend_usd / financials.revenue_usd
            if rd_ratio >= 0.20:
                score += 15
            elif rd_ratio >= 0.10:
                score += 10
            elif rd_ratio >= 0.05:
                score += 5
        
        # Cap at 100
        return min(score, max_score)
    
    def _generate_insights(
        self,
        brand: EnrichedBrand,
        sec_profile: Optional[SECProfile]
    ) -> List[str]:
        """Generate marketing insights from the profile data."""
        insights = []
        
        if not sec_profile or not sec_profile.latest_financials:
            insights.append("No SEC data available - company may be private")
            return insights
        
        financials = sec_profile.latest_financials
        
        # Revenue insights
        if financials.revenue_usd:
            revenue_b = financials.revenue_usd / 1_000_000_000
            if revenue_b >= 100:
                insights.append(f"Fortune 100 company with ${revenue_b:.0f}B revenue")
            elif revenue_b >= 10:
                insights.append(f"Large enterprise with ${revenue_b:.1f}B revenue")
            elif revenue_b >= 1:
                insights.append(f"Mid-market company with ${revenue_b:.1f}B revenue")
            else:
                revenue_m = financials.revenue_usd / 1_000_000
                insights.append(f"Growth company with ${revenue_m:.0f}M revenue")
        
        # Growth insights
        if financials.revenue_growth_yoy is not None:
            if financials.revenue_growth_yoy > 20:
                insights.append(f"High growth: {financials.revenue_growth_yoy:.1f}% YoY revenue growth")
            elif financials.revenue_growth_yoy > 10:
                insights.append(f"Strong growth: {financials.revenue_growth_yoy:.1f}% YoY revenue growth")
            elif financials.revenue_growth_yoy < -10:
                insights.append(f"Declining revenue: {financials.revenue_growth_yoy:.1f}% YoY")
        
        # Employee insights
        if financials.employee_count:
            if financials.employee_count >= 100_000:
                insights.append(f"Major employer with {financials.employee_count:,} employees")
            elif financials.employee_count >= 10_000:
                insights.append(f"Large organization with {financials.employee_count:,} employees")
            elif financials.employee_count >= 1_000:
                insights.append(f"Growing team: {financials.employee_count:,} employees")
        
        # Marketing spend insights
        if financials.marketing_spend_usd and financials.revenue_usd:
            spend_m = financials.marketing_spend_usd / 1_000_000
            spend_pct = (financials.marketing_spend_usd / financials.revenue_usd) * 100
            insights.append(f"Invests ${spend_m:.0f}M annually in marketing ({spend_pct:.1f}% of revenue)")
        
        # R&D insights
        if financials.rd_spend_usd and financials.revenue_usd:
            rd_m = financials.rd_spend_usd / 1_000_000
            rd_pct = (financials.rd_spend_usd / financials.revenue_usd) * 100
            if rd_pct >= 10:
                insights.append(f"Heavy R&D investment: ${rd_m:.0f}M ({rd_pct:.1f}% of revenue)")
            elif rd_pct >= 5:
                insights.append(f"Moderate R&D spend: ${rd_m:.0f}M ({rd_pct:.1f}% of revenue)")
        
        # Industry insights
        if sec_profile.sic_description:
            insights.append(f"Operates in {sec_profile.sic_description} sector")
        
        if sec_profile.exchange:
            insights.append(f"Publicly traded on {sec_profile.exchange}")
        
        # Martech stack insights
        tech_count = len(brand.detected_technologies)
        if tech_count == 0:
            insights.append("Minimal martech stack detected - greenfield opportunity")
        elif tech_count <= 3:
            insights.append(f"Basic martech stack ({tech_count} vendors) - room for expansion")
        elif tech_count >= 10:
            insights.append(f"Sophisticated martech stack ({tech_count} vendors) - mature operation")
        
        return insights
    
    def _generate_recommendations(
        self,
        brand: EnrichedBrand,
        sec_profile: Optional[SECProfile]
    ) -> List[str]:
        """Generate actionable recommendations based on the profile."""
        recommendations = []
        
        if not sec_profile or not sec_profile.latest_financials:
            recommendations.append("Focus on digital marketing stack audit")
            recommendations.append("Consider data enrichment for private company intelligence")
            return recommendations
        
        financials = sec_profile.latest_financials
        
        # Size-based recommendations
        if financials.revenue_usd:
            if financials.revenue_usd >= 10_000_000_000:
                recommendations.append("Enterprise-grade solutions appropriate")
                recommendations.append("Multi-stakeholder sales approach recommended")
            elif financials.revenue_usd >= 1_000_000_000:
                recommendations.append("Mid-market/enterprise hybrid approach")
                recommendations.append("Emphasize scalability and ROI")
            else:
                recommendations.append("Growth-focused value proposition")
                recommendations.append("Emphasize quick time-to-value")
        
        # Marketing spend recommendations
        if financials.marketing_spend_usd and financials.revenue_usd:
            spend_ratio = financials.marketing_spend_usd / financials.revenue_usd
            if spend_ratio < 0.05:
                recommendations.append("Under-invested in marketing - opportunity for budget expansion")
            elif spend_ratio > 0.15:
                recommendations.append("Heavy marketing spend - emphasize efficiency and optimization")
        
        # R&D recommendations
        if financials.rd_spend_usd and financials.revenue_usd:
            rd_ratio = financials.rd_spend_usd / financials.revenue_usd
            if rd_ratio > 0.15:
                recommendations.append("Innovation-focused company - emphasize cutting-edge solutions")
        
        # Martech stack recommendations
        tech_categories = set()
        for tech in brand.detected_technologies:
            cat = tech.get('category', '')
            if cat:
                tech_categories.add(cat)
        
        if 'Analytics' not in tech_categories:
            recommendations.append("No analytics platform detected - high priority opportunity")
        if 'CDP' not in tech_categories and financials.revenue_usd and financials.revenue_usd > 1_000_000_000:
            recommendations.append("Enterprise company without CDP - data unification opportunity")
        if 'Social Media' not in tech_categories:
            recommendations.append("No social media tracking - consider social listening tools")
        
        # Industry-specific recommendations
        if sec_profile.sic_description:
            sic_lower = sec_profile.sic_description.lower()
            if 'retail' in sic_lower or 'electronic' in sic_lower:
                recommendations.append("Retail focus - emphasize customer journey optimization")
            if 'software' in sic_lower or 'computer' in sic_lower:
                recommendations.append("Tech company - technical buyers, emphasize integration")
            if 'health' in sic_lower or 'pharma' in sic_lower:
                recommendations.append("Healthcare vertical - emphasize compliance and privacy")
        
        return recommendations
    
    def _determine_confidence_level(self, brand: EnrichedBrand) -> str:
        """Determine confidence level based on data completeness."""
        if brand.data_completeness >= 0.9:
            return "high"
        elif brand.data_completeness >= 0.6:
            return "medium"
        else:
            return "low"
    
    def build_profile_from_enrichment(
        self,
        domain: str,
        enrichment_result: EnrichmentResult,
        scan_data: Optional[Dict[str, Any]] = None
    ) -> EnrichedBrand:
        """Build profile from an enrichment result.
        
        Convenience method that handles failed enrichments gracefully.
        
        Args:
            domain: Website domain.
            enrichment_result: Result from EdgarClient.enrich_* methods.
            scan_data: Optional scan data to combine.
            
        Returns:
            EnrichedBrand profile (may have limited data if enrichment failed).
        """
        if enrichment_result.success and enrichment_result.brand:
            # Start with the enrichment result brand
            brand = enrichment_result.brand
            
            # Always update domain
            brand.domain = domain
            
            # Update with scan data if provided
            if scan_data:
                detected = scan_data.get('detected_technologies', [])
                if not detected and 'vendors' in scan_data:
                    detected = [
                        {'vendor': v.get('vendor_name', 'Unknown'),
                         'category': v.get('category', 'Unknown')}
                        for v in scan_data.get('vendors', [])
                    ]
                brand.detected_technologies = detected
            
            # Recalculate score, insights and recommendations
            brand.qualification_score = self._calculate_qualification_score(
                brand.sec_profile, brand.detected_technologies
            )
            brand.insights = self._generate_insights(brand, brand.sec_profile)
            brand.recommendations = self._generate_recommendations(
                brand, brand.sec_profile
            )
            brand.data_completeness = self._calculate_data_completeness(
                scan_data or {}, brand.sec_profile
            )
            brand.confidence_level = self._determine_confidence_level(brand)
            
            return brand
        else:
            # Enrichment failed - build profile from scan data only
            logger.warning(f"Enrichment failed for {domain}, building scan-only profile")
            return self.build_profile(
                domain=domain,
                scan_data=scan_data,
                sec_profile=None
            )
