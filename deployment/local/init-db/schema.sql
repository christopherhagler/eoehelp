-- Users Table
CREATE TABLE Users (
    UserID SERIAL PRIMARY KEY,
    Username VARCHAR(255) UNIQUE NOT NULL,
    PasswordHash TEXT NOT NULL,
    Email VARCHAR(255) UNIQUE,
    CreatedAt TIMESTAMP DEFAULT current_timestamp,
    AllowForResearch BOOLEAN DEFAULT FALSE
);

-- Food Items Table
CREATE TABLE FoodItems (
    FoodItemID SERIAL PRIMARY KEY,
    Name VARCHAR(255) NOT NULL,
    Description TEXT
);

-- Meals Table
CREATE TABLE Meals (
    MealID SERIAL PRIMARY KEY,
    UserID INT REFERENCES Users(UserID),
    Name VARCHAR(255) NOT NULL,
    MealDate DATE NOT NULL,
    MealTime TIME NOT NULL
);

-- Allergy Symptoms Table
CREATE TABLE AllergySymptoms (
    SymptomID SERIAL PRIMARY KEY,
    Name VARCHAR(255) NOT NULL,
    Severity TEXT CHECK (Severity IN ('Mild', 'Moderate', 'Severe')) NOT NULL
);

-- Ingredients Table
CREATE TABLE Ingredients (
    IngredientID SERIAL PRIMARY KEY,
    Name VARCHAR(255) NOT NULL,
    Description TEXT
);

-- DietPhases Table
CREATE TABLE DietPhases (
    PhaseID SERIAL PRIMARY KEY,
    Name VARCHAR(255) NOT NULL,
    Description TEXT
);

-- Medications Table
CREATE TABLE Medications (
    MedicationID SERIAL PRIMARY KEY,
    Name VARCHAR(255) NOT NULL,
    Description TEXT,
    Manufacturer VARCHAR(255),
    StartTime TIMESTAMP NOT NULL,
    LastTimeTaken TIMESTAMP,
    DosesPerDay INT NOT NULL
);

-- Endoscopies Table
CREATE TABLE Endoscopies (
    EndoscopyID SERIAL PRIMARY KEY,
    Date DATE NOT NULL,
    Time TIME NOT NULL,
    EosinophilCount INT NOT NULL,
    Description TEXT
);

-- Triggers Table
CREATE TABLE Triggers (
    TriggerID SERIAL PRIMARY KEY,
    Name VARCHAR(255) NOT NULL,
    Description TEXT
);

-- Meal and Food Items Relationship Table
CREATE TABLE Meal_FoodItems (
    MealID INT NOT NULL REFERENCES Meals(MealID),
    FoodItemID INT NOT NULL REFERENCES FoodItems(FoodItemID),
    PRIMARY KEY (MealID, FoodItemID)
);

-- Meal and Allergy Symptoms Relationship Table
CREATE TABLE Meal_AllergySymptoms (
    MealID INT NOT NULL REFERENCES Meals(MealID),
    SymptomID INT NOT NULL REFERENCES AllergySymptoms(SymptomID),
    OccurredAt TIMESTAMP NOT NULL,
    PRIMARY KEY (MealID, SymptomID, OccurredAt)
);

-- Food Item and Ingredients Relationship Table
CREATE TABLE FoodItem_Ingredients (
    FoodItemID INT NOT NULL REFERENCES FoodItems(FoodItemID),
    IngredientID INT NOT NULL REFERENCES Ingredients(IngredientID),
    PRIMARY KEY (FoodItemID, IngredientID)
);

-- User and Medications Relationship Table
CREATE TABLE User_Medications (
    UserID INT NOT NULL REFERENCES Users(UserID),
    MedicationID INT NOT NULL REFERENCES Medications(MedicationID),
    PRIMARY KEY (UserID, MedicationID)
);

-- User and Endoscopies Relationship Table
CREATE TABLE User_Endoscopies (
    UserID INT NOT NULL REFERENCES Users(UserID),
    EndoscopyID INT NOT NULL REFERENCES Endoscopies(EndoscopyID),
    PRIMARY KEY (UserID, EndoscopyID)
);

-- User and Triggers Relationship Table
CREATE TABLE User_Triggers (
    UserID INT NOT NULL REFERENCES Users(UserID),
    TriggerID INT NOT NULL REFERENCES Triggers(TriggerID),
    PRIMARY KEY (UserID, TriggerID)
);

-- User and DietPhases Relationship Table
CREATE TABLE User_DietPhases (
    UserID INT NOT NULL REFERENCES Users(UserID),
    PhaseID INT NOT NULL REFERENCES DietPhases(PhaseID),
    StartDate DATE NOT NULL,
    EndDate DATE,
    PRIMARY KEY (UserID, PhaseID, StartDate)
);

