@SPEC-PIPE-001
Feature: Datos reales de la pipeline de Data Quality

  Como responsable del dataset
  quiero que la Web App muestre y edite los datos reales de la pipeline
  para dejar de depender de los mocks estáticos de APP-01.

  Scenario: El reporte de calidad se lee tal como lo dejó la pipeline
    Given pipeline/data/interim/quality.json existe con un overall_status "fail"
    When se pide GET /quality-report
    Then la respuesta trae ese mismo overall_status "fail"

  Scenario: Un contrato que todavía no existe da un error claro, no un 500 genérico
    Given pipeline/data/interim/quality.json no existe todavía
    When se pide GET /quality-report
    Then la respuesta es 404 con un mensaje que dice que hay que correr la pipeline

  Scenario: dvc repro sí cambia lo que ve la Web App (corrección de revisión, Mau)
    Given contracts/quality.json existe con un overall_status "pass" (el mock viejo, sin tocar)
    And pipeline/data/interim/quality.json no existe todavía
    When se corre la pipeline (dvc repro) y produce pipeline/data/interim/quality.json con overall_status "fail"
    And se pide GET /quality-report
    Then la respuesta trae overall_status "fail", nunca el "pass" del mock de contracts/

  Scenario: La política se lee de quality.yaml, no del último reporte
    Given pipeline/quality.yaml tiene min_images_per_class con threshold 300
    When se pide GET /quality-policy
    Then la respuesta trae min_images_per_class.threshold igual a 300

  Scenario: Settings puede subir un threshold y persiste
    Given pipeline/quality.yaml tiene class_imbalance con threshold 3.0
    When se manda PUT /quality-policy con class_imbalance.threshold en 4.5 y el resto de checks sin cambio
    Then la respuesta trae class_imbalance.threshold igual a 4.5
    And una lectura posterior de GET /quality-policy también trae 4.5

  Scenario: Settings no puede bajar min_images_per_class de 300
    Given pipeline/quality.yaml tiene min_images_per_class con threshold 300
    When se manda PUT /quality-policy con min_images_per_class.threshold en 100
    Then la respuesta es 400
    And pipeline/quality.yaml no cambia

  Scenario: Settings no puede agregar ni quitar checks
    Given pipeline/quality.yaml tiene exactamente los checks A y B
    When se manda PUT /quality-policy con los checks A y C
    Then la respuesta es 400

  Scenario: label, comparison y unit nunca cambian por una edición de Settings
    Given class_imbalance tiene label "Class imbalance ratio" y unit "majority/minority ratio"
    When se manda PUT /quality-policy cambiando solo threshold y severity de class_imbalance
    Then class_imbalance conserva su label y su unit sin cambios
