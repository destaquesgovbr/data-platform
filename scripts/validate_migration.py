#!/usr/bin/env python3
"""
Validate migration from HuggingFace to PostgreSQL.

This script validates that data was correctly migrated by:
- Comparing record counts
- Checking data integrity
- Sampling records for consistency
- Generating validation report

Usage:
    python scripts/validate_migration.py
    python scripts/validate_migration.py --sample-size 100
    python scripts/validate_migration.py --dataset nitaibezerra/govbrnews
"""

import argparse
import sys
from pathlib import Path
from typing import Dict, Any, List
import random

from datasets import load_dataset
from loguru import logger
from tabulate import tabulate

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from data_platform.managers import PostgresManager


def validate_counts(
    dataset_name: str, manager: PostgresManager
) -> Dict[str, Any]:
    """
    Compare record counts between HuggingFace and PostgreSQL.

    Args:
        dataset_name: HuggingFace dataset name
        manager: PostgresManager instance

    Returns:
        Dictionary with count validation results
    """
    logger.info("Validating record counts...")

    # Load HuggingFace dataset
    logger.info(f"Loading dataset: {dataset_name}")
    dataset = load_dataset(dataset_name, split="train")
    hf_count = len(dataset)

    # Get PostgreSQL count
    pg_count = manager.count()

    # Calculate difference
    diff = pg_count - hf_count
    diff_pct = (diff / hf_count * 100) if hf_count > 0 else 0

    result = {
        "hf_count": hf_count,
        "pg_count": pg_count,
        "difference": diff,
        "difference_pct": diff_pct,
        "match": diff == 0,
    }

    # Log results
    logger.info(f"HuggingFace count: {hf_count:,}")
    logger.info(f"PostgreSQL count:  {pg_count:,}")
    logger.info(f"Difference:        {diff:,} ({diff_pct:+.2f}%)")

    if result["match"]:
        logger.success("✓ Counts match!")
    else:
        logger.warning(f"✗ Count mismatch: {diff:,} records")

    return result


def validate_integrity(manager: PostgresManager) -> Dict[str, Any]:
    """
    Validate data integrity in PostgreSQL.

    Args:
        manager: PostgresManager instance

    Returns:
        Dictionary with integrity validation results
    """
    logger.info("\nValidating data integrity...")

    conn = manager.get_connection()
    cursor = conn.cursor()

    results = {}

    try:
        # 1. Check for NULL required fields
        logger.info("Checking required fields...")
        cursor.execute(
            """
            SELECT COUNT(*) FROM news
            WHERE unique_id IS NULL
               OR agency_id IS NULL
               OR title IS NULL
               OR published_at IS NULL
        """
        )
        null_required = cursor.fetchone()[0]
        results["null_required_fields"] = null_required

        # 2. Check agency_id validity
        logger.info("Checking agency_id references...")
        cursor.execute(
            """
            SELECT COUNT(*) FROM news
            WHERE agency_id NOT IN (SELECT id FROM agencies)
        """
        )
        invalid_agencies = cursor.fetchone()[0]
        results["invalid_agencies"] = invalid_agencies

        # 3. Check theme_id validity
        logger.info("Checking theme_id references...")
        cursor.execute(
            """
            SELECT COUNT(*) FROM news
            WHERE (theme_l1_id IS NOT NULL AND theme_l1_id NOT IN (SELECT id FROM themes))
               OR (theme_l2_id IS NOT NULL AND theme_l2_id NOT IN (SELECT id FROM themes))
               OR (theme_l3_id IS NOT NULL AND theme_l3_id NOT IN (SELECT id FROM themes))
               OR (most_specific_theme_id IS NOT NULL AND most_specific_theme_id NOT IN (SELECT id FROM themes))
        """
        )
        invalid_themes = cursor.fetchone()[0]
        results["invalid_themes"] = invalid_themes

        # 4. Check unique_id uniqueness
        logger.info("Checking unique_id uniqueness...")
        cursor.execute(
            """
            SELECT COUNT(*) FROM (
                SELECT unique_id, COUNT(*) as cnt
                FROM news
                GROUP BY unique_id
                HAVING COUNT(*) > 1
            ) duplicates
        """
        )
        duplicate_unique_ids = cursor.fetchone()[0]
        results["duplicate_unique_ids"] = duplicate_unique_ids

        # 5. Count records with themes
        logger.info("Checking theme coverage...")
        cursor.execute("SELECT COUNT(*) FROM news WHERE most_specific_theme_id IS NOT NULL")
        with_theme = cursor.fetchone()[0]
        total = manager.count()
        theme_pct = (with_theme / total * 100) if total > 0 else 0
        results["records_with_theme"] = with_theme
        results["theme_coverage_pct"] = theme_pct

        # 6. Check denormalized fields consistency
        logger.info("Checking denormalized field consistency...")
        cursor.execute(
            """
            SELECT COUNT(*) FROM news n
            JOIN agencies a ON n.agency_id = a.id
            WHERE n.agency_key != a.key
               OR n.agency_name != a.name
        """
        )
        inconsistent_denorm = cursor.fetchone()[0]
        results["inconsistent_denormalized"] = inconsistent_denorm

    finally:
        cursor.close()
        manager.put_connection(conn)

    # Log results
    logger.info(f"\nNull required fields:       {results['null_required_fields']}")
    logger.info(f"Invalid agency references:  {results['invalid_agencies']}")
    logger.info(f"Invalid theme references:   {results['invalid_themes']}")
    logger.info(f"Duplicate unique_ids:       {results['duplicate_unique_ids']}")
    logger.info(f"Records with theme:         {results['records_with_theme']:,} ({results['theme_coverage_pct']:.1f}%)")
    logger.info(f"Inconsistent denorm fields: {results['inconsistent_denormalized']}")

    # Check if all validations passed
    all_pass = (
        results["null_required_fields"] == 0
        and results["invalid_agencies"] == 0
        and results["invalid_themes"] == 0
        and results["duplicate_unique_ids"] == 0
        and results["inconsistent_denormalized"] == 0
        and results["theme_coverage_pct"] >= 95
    )

    results["all_pass"] = all_pass

    if all_pass:
        logger.success("\n✓ All integrity checks passed!")
    else:
        logger.warning("\n✗ Some integrity checks failed")

    return results


def sample_records(
    dataset_name: str, manager: PostgresManager, sample_size: int = 10
) -> Dict[str, Any]:
    """
    Sample records to verify consistency between HF and PG.

    Args:
        dataset_name: HuggingFace dataset name
        manager: PostgresManager instance
        sample_size: Number of records to sample

    Returns:
        Dictionary with sampling results
    """
    logger.info(f"\nSampling {sample_size} records for consistency check...")

    # Load HuggingFace dataset
    dataset = load_dataset(dataset_name, split="train")

    # Sample random indices
    indices = random.sample(range(len(dataset)), min(sample_size, len(dataset)))

    results = {
        "sampled": 0,
        "matched": 0,
        "mismatched": 0,
        "not_found": 0,
    }

    for idx in indices:
        row = dataset[idx]
        unique_id = row.get("unique_id")

        if not unique_id:
            continue

        results["sampled"] += 1

        # Get from PostgreSQL
        news = manager.get_by_unique_id(unique_id)

        if not news:
            logger.warning(f"✗ Record not found in PG: {unique_id}")
            results["not_found"] += 1
            continue

        # Compare key fields
        title_match = news.title == row.get("title")
        agency_match = news.agency_key == row.get("agency")

        if title_match and agency_match:
            results["matched"] += 1
        else:
            results["mismatched"] += 1
            logger.warning(
                f"✗ Mismatch for {unique_id}: "
                f"title={title_match}, agency={agency_match}"
            )

    # Calculate percentage
    match_pct = (results["matched"] / results["sampled"] * 100) if results["sampled"] > 0 else 0

    logger.info(f"\nSample results:")
    logger.info(f"  Sampled:    {results['sampled']}")
    logger.info(f"  Matched:    {results['matched']} ({match_pct:.1f}%)")
    logger.info(f"  Mismatched: {results['mismatched']}")
    logger.info(f"  Not found:  {results['not_found']}")

    results["match_pct"] = match_pct

    if match_pct == 100:
        logger.success("✓ All sampled records match!")
    else:
        logger.warning(f"✗ {results['mismatched'] + results['not_found']} records have issues")

    return results


def generate_report(
    count_results: Dict[str, Any],
    integrity_results: Dict[str, Any],
    sample_results: Dict[str, Any],
) -> None:
    """
    Generate validation report.

    Args:
        count_results: Count validation results
        integrity_results: Integrity validation results
        sample_results: Sample validation results
    """
    logger.info("\n" + "=" * 60)
    logger.info("VALIDATION REPORT")
    logger.info("=" * 60)

    # Count comparison
    count_table = [
        ["HuggingFace", f"{count_results['hf_count']:,}"],
        ["PostgreSQL", f"{count_results['pg_count']:,}"],
        ["Difference", f"{count_results['difference']:,} ({count_results['difference_pct']:+.2f}%)"],
        ["Status", "✓ Match" if count_results["match"] else "✗ Mismatch"],
    ]

    logger.info("\n## Record Counts")
    logger.info("\n" + tabulate(count_table, headers=["Source", "Count"], tablefmt="simple"))

    # Integrity checks
    integrity_table = [
        ["NULL required fields", integrity_results["null_required_fields"], "✓" if integrity_results["null_required_fields"] == 0 else "✗"],
        ["Invalid agencies", integrity_results["invalid_agencies"], "✓" if integrity_results["invalid_agencies"] == 0 else "✗"],
        ["Invalid themes", integrity_results["invalid_themes"], "✓" if integrity_results["invalid_themes"] == 0 else "✗"],
        ["Duplicate unique_ids", integrity_results["duplicate_unique_ids"], "✓" if integrity_results["duplicate_unique_ids"] == 0 else "✗"],
        ["Theme coverage", f"{integrity_results['theme_coverage_pct']:.1f}%", "✓" if integrity_results["theme_coverage_pct"] >= 95 else "✗"],
        ["Inconsistent denorm", integrity_results["inconsistent_denormalized"], "✓" if integrity_results["inconsistent_denormalized"] == 0 else "✗"],
    ]

    logger.info("\n## Data Integrity")
    logger.info("\n" + tabulate(integrity_table, headers=["Check", "Value", "Status"], tablefmt="simple"))

    # Sample consistency
    sample_table = [
        ["Sampled records", sample_results["sampled"]],
        ["Matched", f"{sample_results['matched']} ({sample_results['match_pct']:.1f}%)"],
        ["Mismatched", sample_results["mismatched"]],
        ["Not found", sample_results["not_found"]],
    ]

    logger.info("\n## Sample Consistency")
    logger.info("\n" + tabulate(sample_table, headers=["Metric", "Value"], tablefmt="simple"))

    # Overall status
    logger.info("\n" + "=" * 60)

    all_pass = (
        count_results["match"]
        and integrity_results["all_pass"]
        and sample_results["match_pct"] == 100
    )

    if all_pass:
        logger.success("✓ MIGRATION VALIDATED SUCCESSFULLY")
    else:
        logger.error("✗ MIGRATION HAS ISSUES - PLEASE REVIEW")

    logger.info("=" * 60)


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Validate migration from HuggingFace to PostgreSQL"
    )
    parser.add_argument(
        "--dataset",
        type=str,
        default="nitaibezerra/govbrnews",
        help="HuggingFace dataset name (default: nitaibezerra/govbrnews)",
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        default=100,
        help="Number of records to sample (default: 100)",
    )
    args = parser.parse_args()

    # Configure logger
    logger.remove()
    logger.add(
        sys.stdout,
        colorize=True,
        format="<level>{level: <8}</level> | <cyan>{message}</cyan>",
    )

    logger.info("=" * 60)
    logger.info("Validate HuggingFace → PostgreSQL Migration")
    logger.info("=" * 60)

    # Initialize PostgresManager
    with PostgresManager() as manager:
        manager.load_cache()

        # Run validations
        count_results = validate_counts(args.dataset, manager)
        integrity_results = validate_integrity(manager)
        sample_results = sample_records(args.dataset, manager, args.sample_size)

        # Generate report
        generate_report(count_results, integrity_results, sample_results)

    # Exit code
    all_pass = (
        count_results["match"]
        and integrity_results["all_pass"]
        and sample_results["match_pct"] == 100
    )

    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()
