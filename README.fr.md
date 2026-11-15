# Skolengo (ENT) pour Home Assistant

> **Projet non officiel.** Sans lien avec Kosmos, ni approuvé ou soutenu par Kosmos.
> « Skolengo » est une marque de son propriétaire.

🇬🇧 [English version](README.md)

Intégration personnalisée Home Assistant pour **Skolengo**, l'ENT de Kosmos utilisé par de nombreuses
régions (par exemple *Mon ENT Occitanie*). Elle utilise la même API que l'application mobile Skolengo.

## État

🚧 **En développement, pas encore utilisable.** L'avancement est suivi dans les
[tickets](https://github.com/sylvaing/ha-skolengo/issues) et les
[jalons](https://github.com/sylvaing/ha-skolengo/milestones).

## Fonctions prévues (v0.1.0)

Pour chaque élève, seulement pour les services ouverts par son établissement :

- **Devoirs** (cahier de textes) : un capteur et une liste de tâches ; cocher un devoir le marque comme
  fait dans l'ENT.
- **Emploi du temps** : un capteur et un calendrier (matières, salles, professeurs, cours annulés).
- **Messagerie** : capteur des messages non lus avec les derniers messages.
- **Cartes Lovelace** livrées avec l'intégration : `skolengo-homework-card`, `skolengo-timetable-card`,
  `skolengo-messages-card`.

Connexion : choisissez votre établissement et votre fournisseur d'identité, puis tapez votre identifiant
et votre mot de passe **EduConnect**. L'intégration se connecte elle-même, sans navigateur ; le mot de
passe n'est pas conservé, seul le jeton de renouvellement l'est.

Les notes et les absences ne sont pas dans la v0.1.0 : dans les établissements qui utilisent Pronote,
Skolengo ne fait que les relayer et l'API échoue souvent. L'[intégration Pronote](https://github.com/delphiki/hass-pronote)
les couvre.

## Documentation

- [API mobile Skolengo — référence non officielle](docs/skolengo-api.md) (en anglais)

## Installation

Pas encore disponible. À la sortie de la v0.1.0, elle s'installera par [HACS](https://hacs.xyz) comme
dépôt personnalisé.

## Confidentialité

Votre mot de passe EduConnect n'est envoyé qu'à EduConnect (`educonnect.education.gouv.fr`) au moment de
la connexion, et n'est pas conservé. Les jetons de session sont stockés uniquement dans Home Assistant et
envoyés uniquement à votre ENT et à l'API Skolengo (`api.skolengo.com`), comme le fait l'application.
L'intégration lit les données scolaires de vos enfants : limitez l'accès à votre Home Assistant en
conséquence.

## Licence

[MIT](LICENSE)
