# Checklist push-ready

## 1) Décisions de produit / conception

Ces points ne sont pas des bugs à corriger immédiatement. Ils expriment la maturité fonctionnelle et le cadrage métier actuel.

1. Le reste à faire n'est pas calculé automatiquement ; il est ré-estimé manuellement par l'utilisateur et servira ensuite à calculer l'avancement et les coûts à terminaison.
2. La solution la plus simple consiste à refuser les devises différentes ; les taux horaires doivent rester dans la devise courante.
3. La page projet n'est pas finalisée. Il est trop tôt pour lancer des tests d'intégration sur cette page. En revanche, la page ressource est assez avancée pour servir de base à des tests d'intégration.

## 2) Correctifs à traiter avant le push

Ces éléments doivent être corrigés avant tout push sérieux.

4. À corriger
5. À corriger
7. À corriger
8. À corriger
10. À corriger
11. À corriger
12. À corriger
13. À corriger
14. À corriger

## 3) Points à vérifier avant validation finale

6. L'inflation est à confirmer avec la règle métier. Si elle est correctement appliquée, ce n'est pas forcément un problème. Il faut valider le comportement et sa cohérence avec le calcul de coût et de budget.

## 4) Points à reporter

9. Noté ; remettre plus tard.
16. Remettre à plus tard.

## 5) Points acceptables à ce stade

15. Acceptable à ce stade.

## 6) Suggestions de maintenabilité à préserver

Les recommandations de maintenabilité sont utiles et doivent être gardées dans la liste de travail. Elles réduisent la dette technique et évitent des régressions coûteuses plus tard.

- Clarifier les responsabilités entre couche métier et couche UI.
- Séparer clairement les règles de calcul/validation des règles de présentation.
- Réduire les dépendances implicites entre écrans et services.
- Préserver des tests de régression sur les domaines métier sensibles.
- Garder les conventions de nommage et la cohérence des schémas API.

## 7) Priorisation recommandée

### Must fix before push
- 4, 5, 7, 8, 10, 11, 12, 13, 14

### Verify before final sign-off
- 6

### Deferred
- 9, 16

### Acceptable now
- 15

### Product decisions
- 1, 2, 3
