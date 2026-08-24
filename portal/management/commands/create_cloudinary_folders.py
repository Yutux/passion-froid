from django.core.management.base import BaseCommand

from portal.cloudinary_medallion import configure_cloudinary, create_medallion_folders


class Command(BaseCommand):
    help = "Crée les 3 dossiers Medallion (bronze, silver, gold) sur Cloudinary"

    def handle(self, *args, **options):
        self.stdout.write("📁 Connexion à Cloudinary...")
        configure_cloudinary()

        self.stdout.write("🚀 Création des dossiers Medallion...\n")
        results = create_medallion_folders()

        icons = {"created": "✅", "exists": "⚠️ ", "error": "❌"}
        for folder, info in results.items():
            icon = icons.get(info["status"], "❓")
            self.stdout.write(f"  {icon}  {info['message']}")

        errors = [k for k, v in results.items() if v["status"] == "error"]
        if errors:
            self.stderr.write(f"\n❌ Erreurs sur : {', '.join(errors)}")
            self.stderr.write("Vérifiez vos clés dans .env")
        else:
            self.stdout.write(self.style.SUCCESS("\n✔ Tous les dossiers Cloudinary sont prêts !"))
            self.stdout.write("  🥉 bronze/  →  fichiers bruts (originaux)")
            self.stdout.write("  🥈 silver/  →  normalisés (EXIF supprimé, format auto)")
            self.stdout.write("  🥇 gold/    →  optimisés pour la production CDN")
